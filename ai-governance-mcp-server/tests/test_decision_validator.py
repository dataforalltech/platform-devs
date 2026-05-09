"""Testes da regra mais crítica: validate_agent_decision.

Cada teste corresponde a uma das proibições da política — se a regra parar de
pegar o caso, o teste falha e o agente passaria a aprovar uma decisão perigosa.
"""

from __future__ import annotations

import pytest

from src.tools.decision_tool import validate_agent_decision


# --------------------------- bloqueios CRITICAL --------------------------- #
def test_blocks_silent_fallback_pattern(repo):
    res = validate_agent_decision(
        repo,
        repository_name="orders-service",
        task_description="ajustar chamada ao provider de pagamento",
        proposed_change=(
            "try:\n"
            "    return provider.charge(amount)\n"
            "except Exception:\n"
            "    pass\n"
        ),
    )
    assert res["approved"] is False
    assert res["risk_level"] == "critical"
    assert any("silencioso" in v.lower() for v in res["violations"])


def test_blocks_hardcoded_token(repo):
    res = validate_agent_decision(
        repo,
        repository_name="orders-service",
        task_description="adicionar integração com novo provider",
        proposed_change='api_key = "sk-1234567890abcdef1234"',
    )
    assert res["approved"] is False
    assert res["risk_level"] == "critical"
    assert any("hardcoded" in v.lower() or "credencial" in v.lower() for v in res["violations"])


def test_blocks_auth_bypass(repo):
    res = validate_agent_decision(
        repo,
        repository_name="api-gateway",
        task_description="permitir bypass auth para endpoint de saúde",
        proposed_change="if request.headers.get('X-Skip-Auth'): return handler()",
        modifies_security=True,
    )
    assert res["approved"] is False
    assert res["risk_level"] == "critical"


def test_blocks_mock_in_prod(repo):
    res = validate_agent_decision(
        repo,
        repository_name="payment-service",
        task_description="contornar provider caído",
        proposed_change="if env.PARTNER_DOWN: return MockProvider().charge(amount)",
    )
    assert res["approved"] is False
    assert any("mock" in v.lower() or "fake" in v.lower() for v in res["violations"])


def test_blocks_test_deletion(repo):
    res = validate_agent_decision(
        repo,
        repository_name="orders-service",
        task_description="fazer build passar",
        proposed_change="apaguei o teste tests/test_payment.py que estava falhando",
    )
    assert res["approved"] is False
    assert any("teste" in v.lower() for v in res["violations"])


def test_blocks_destructive_db(repo):
    res = validate_agent_decision(
        repo,
        repository_name="orders-service",
        task_description="limpar dados antigos",
        proposed_change="session.execute(text('DROP TABLE legacy_orders'))",
        affected_layers=["database"],
    )
    assert res["approved"] is False
    assert res["risk_level"] == "critical"


def test_blocks_fallback_without_observability(repo):
    res = validate_agent_decision(
        repo,
        repository_name="user-service",
        task_description="adicionar fallback no perfil",
        proposed_change="return cache.get(user_id)  # se provider falha",
        adds_fallback=True,
    )
    assert res["approved"] is False
    assert any("observabilidade" in v.lower() or "métrica" in v.lower() for v in res["violations"])


# --------------------------- HIGH risk (não bloqueia) --------------------------- #
def test_contract_change_without_consumers_is_high(repo):
    res = validate_agent_decision(
        repo,
        repository_name="orders",
        task_description="alterar payload do /orders",
        proposed_change="adicionar campo opcional",
        affected_layers=["backend"],
        changes_contracts=True,
    )
    assert res["approved"] is True  # não bloqueia, mas marca high risk
    assert res["risk_level"] == "high"
    assert any("consumidor" in v.lower() for v in res["violations"])


def test_contract_change_with_consumers_lower_risk(repo):
    res = validate_agent_decision(
        repo,
        repository_name="orders",
        task_description="alterar payload do /orders impactando consumidor frontend",
        proposed_change="adicionar campo opcional; atualizei consumidor frontend",
        affected_layers=["backend"],
        changes_contracts=True,
    )
    assert res["risk_level"] in ("medium", "low")


def test_dependency_without_justification_is_high(repo):
    res = validate_agent_decision(
        repo,
        repository_name="x",
        task_description="adicionar nova lib",
        proposed_change="adicionei a dependency rare-utils ao requirements.txt",
        adds_dependency=True,
    )
    assert res["risk_level"] == "high"
    assert any("dependência" in v.lower() for v in res["violations"])


def test_dependency_pattern_does_not_trigger_on_literal_mention(repo):
    """Regression (ADR-0004): mencionar 'pyproject.toml' em string literal/docstring
    sem verbo de modificação NÃO deve disparar regra de dependência."""
    res = validate_agent_decision(
        repo,
        repository_name="x",
        task_description="renomear variável local",
        proposed_change=(
            "Detector que olha {'pyproject.toml', 'requirements.txt'} para "
            "saber se é manifest de deps. Não estou modificando nenhum desses arquivos."
        ),
        affected_files=["scripts/some_script.py"],
    )
    # Sem verbo de modificação → não dispara regra de dependência
    assert not any("dependência" in v.lower() for v in res["violations"])


def test_dependency_pattern_still_fires_with_verb_context(repo):
    """Garante que a fix do regex não enfraqueceu a regra: verbo + manifesto ainda dispara."""
    res = validate_agent_decision(
        repo,
        repository_name="x",
        task_description="task",
        proposed_change="adicionei a lib X em pyproject.toml",
    )
    # adds_dependency=False mas o regex deve pegar via 4º pattern
    assert any("dependência" in v.lower() for v in res["violations"])


def test_scope_drift_flagged(repo):
    res = validate_agent_decision(
        repo,
        repository_name="x",
        task_description="corrigir bug X",
        proposed_change="corrigi o bug X e aproveitei para refatorar de quebra o módulo Y",
    )
    assert res["risk_level"] == "high"
    assert any("escopo" in v.lower() for v in res["violations"])


def test_integrations_layer_missing_timeout(repo):
    res = validate_agent_decision(
        repo,
        repository_name="x",
        task_description="chamar provider externo",
        proposed_change="response = requests.get(url)",
        affected_layers=["integrations"],
    )
    assert res["risk_level"] == "high"


# --------------------------- caminho feliz --------------------------- #
def test_safe_change_is_approved(repo):
    res = validate_agent_decision(
        repo,
        repository_name="orders-service",
        task_description="renomear variável local em função privada",
        proposed_change="rename local var `x` to `order_id` in `_validate_order`; nada externo muda",
        affected_files=["app/services/order_validator.py"],
        affected_layers=["backend"],
    )
    assert res["approved"] is True
    assert res["risk_level"] in ("low", "medium")
    assert res["violations"] == []


# --------------------------- negação no contexto --------------------------- #
def test_negated_test_deletion_is_not_violation(repo):
    """'Não removi teste' não deve disparar a regra de delete-tests."""
    res = validate_agent_decision(
        repo,
        repository_name="orders-service",
        task_description="adicionar bugfix com regressão",
        proposed_change="Não removi teste; ao contrário, criei 40 testes novos.",
    )
    # nenhuma violation deve mencionar remoção de teste
    assert not any("teste" in v.lower() and "remoção" in v.lower() for v in res["violations"])
    assert not any(
        "indicação de remoção" in v.lower() or "skip de teste" in v.lower()
        for v in res["violations"]
    )


def test_unnegated_test_deletion_still_blocked(repo):
    """Garante que a fix de negação não enfraqueceu a regra: 'removi teste' sem
    negação ainda bloqueia."""
    res = validate_agent_decision(
        repo,
        repository_name="orders-service",
        task_description="ajustar build",
        proposed_change="removi teste flaky para destravar pipeline",
    )
    assert res["approved"] is False
    assert any("teste" in v.lower() for v in res["violations"])


def test_negated_silent_fallback_is_not_violation(repo):
    res = validate_agent_decision(
        repo,
        repository_name="x",
        task_description="ajuste seguro",
        proposed_change="Sem fallback silencioso. Propago a exceção com log.exception.",
    )
    assert res["approved"] is True


# --------------------------- inputs inválidos --------------------------- #
def test_requires_repository_name(repo):
    with pytest.raises(ValueError):
        validate_agent_decision(
            repo,
            repository_name="",
            task_description="x",
            proposed_change="y",
        )


def test_requires_task_and_change(repo):
    with pytest.raises(ValueError):
        validate_agent_decision(
            repo,
            repository_name="x",
            task_description="",
            proposed_change="y",
        )
    with pytest.raises(ValueError):
        validate_agent_decision(
            repo,
            repository_name="x",
            task_description="y",
            proposed_change="",
        )
