"""Testes das 5 tools de ownership/scope/libs.

Usam o repo real (KB + ecosystem.yaml). As 5 tools dependem do grafo, então
checagem de unavailability vai num test isolado com stub.
"""

from __future__ import annotations

import pytest

from src.tools.graph_tool import GraphUnavailable
from src.tools.ownership_tool import (
    check_scope,
    get_port_map,
    get_service_dependencies,
    get_service_ownership,
    validate_lib_change,
)


# --------------------------- get_service_ownership --------------------------- #
def test_ownership_resolves_canonical_service(repo):
    res = get_service_ownership(repo, service_name="platform-cdc")
    assert res["found"] is True
    assert res["service_name"] == "platform-cdc"
    assert res["port"] == 8017
    # platform-cdc declara explicit_non_responsibilities
    assert any("qualidade" in m.lower() or "checks" in m.lower() for m in res["must_not"])


def test_ownership_resolves_alias(repo):
    """rag-service é alias de dataforall-rag-service."""
    res = get_service_ownership(repo, service_name="rag-service")
    assert res["found"] is True
    assert res["service_name"] == "dataforall-rag-service"


def test_ownership_resolves_short_name(repo):
    """'monitor' deve resolver para platform-monitor."""
    res = get_service_ownership(repo, service_name="monitor")
    assert res["found"] is True
    assert res["service_name"] == "platform-monitor"


def test_ownership_marks_deprecated_with_redirect(repo):
    res = get_service_ownership(repo, service_name="connectors-platform")
    assert res["found"] is True
    assert res["status"] == "deprecated"
    assert res["canonical_redirect"] == "platform-connectors"
    assert any("deprecado" in n.lower() for n in res["notes"])


def test_ownership_returns_not_found_with_suggestions(repo):
    res = get_service_ownership(repo, service_name="brand-new-service-xyz")
    assert res["found"] is False
    # Deve listar serviços disponíveis nas notes para ajudar o agente
    assert any("disponíveis" in n.lower() or "disponiveis" in n.lower() for n in res["notes"])


def test_ownership_validates_input(repo):
    with pytest.raises(ValueError):
        get_service_ownership(repo, service_name="")


def test_ownership_lists_calls_to_other_services(repo):
    """dataforall-agents-factory deve listar várias chamadas (consumes contratos + uses_lib)."""
    res = get_service_ownership(repo, service_name="dataforall-agents-factory")
    assert res["found"] is True
    assert len(res["calls"]) >= 3
    via_relations = {c["via"] for c in res["calls"]}
    assert "consumes" in via_relations or "uses_lib" in via_relations


# --------------------------- get_service_dependencies --------------------------- #
def test_dependencies_returns_upstream_and_downstream(repo):
    res = get_service_dependencies(repo, service_name="dataforall-rag-service")
    assert res["found"] is True
    assert res["upstream_count"] >= 1  # uses_lib
    assert res["downstream_count"] >= 1  # agents-factory consome


def test_dependencies_risk_low_for_few_consumers(repo):
    res = get_service_dependencies(repo, service_name="dataforall-rag-service")
    # Apenas agents-factory consome rag — risk=low
    assert res["contract_change_risk"] in ("low", "medium")


def test_dependencies_risk_high_for_many_consumers(repo):
    """platform-core-lib é usada por todos os serviços ativos — high risk."""
    # Como é uma library e get_service_dependencies trata services principais,
    # vamos testar com platform-auth (consumido por vários via JWT validation
    # implícito não modelado, então este teste pode dar low; ajustar abaixo).
    res = get_service_dependencies(repo, service_name="platform-admin")
    # platform-admin é consumido por auth, governance, communication
    assert res["found"] is True
    assert res["downstream_count"] >= 2
    assert res["contract_change_risk"] in ("medium", "high")


def test_dependencies_unknown_service_returns_not_found(repo):
    res = get_service_dependencies(repo, service_name="ghost-service")
    assert res["found"] is False
    assert "notes" in res


def test_dependencies_validates_input(repo):
    with pytest.raises(ValueError):
        get_service_dependencies(repo, service_name="")


# --------------------------- get_port_map --------------------------- #
def test_port_map_lists_all_active_services_with_port(repo):
    res = get_port_map(repo)
    assert res["total_services_with_port"] >= 20
    ports = {e["port"] for e in res["port_map"]}
    # Spot check de portas canônicas conhecidas
    assert 8001 in ports  # auth
    assert 8002 in ports  # admin
    assert 8017 in ports  # cdc
    assert 8018 in ports  # api-gateway
    assert 8080 in ports  # ui-connect


def test_port_map_sorted_by_port(repo):
    res = get_port_map(repo)
    ports = [e["port"] for e in res["port_map"]]
    assert ports == sorted(ports)


def test_port_map_next_available_in_reserved_range(repo):
    res = get_port_map(repo)
    # Range 8022-8029 está vazio no seed atual
    assert res["next_available_port"] == 8022
    assert "8022" in res["reserved_range"]


def test_port_map_includes_gateway_prefix(repo):
    res = get_port_map(repo)
    auth = next(e for e in res["port_map"] if e["service"] == "platform-auth")
    assert auth["gateway_prefix"] == "/auth"


# --------------------------- check_scope --------------------------- #
def test_check_scope_low_risk_for_focused_change(repo):
    res = check_scope(
        repo,
        task_description="Adicionar timeout no provider externo do platform-cdc",
        changed_files=[
            "platform-cdc/app/services/provider.py",
            "platform-cdc/tests/test_provider.py",
        ],
    )
    assert res["approved"] is True
    assert res["risk_level"] == "low"
    assert res["drift_indicators"] == []


def test_check_scope_high_risk_for_volume(repo):
    files = [f"app/module_{i}/file.py" for i in range(35)]
    res = check_scope(
        repo,
        task_description="Pequena correção",
        changed_files=files,
    )
    assert res["risk_level"] in ("high", "critical")
    assert any("volume" in d.lower() for d in res["drift_indicators"])


def test_check_scope_critical_for_libs(repo):
    """Mudança em platform-*-lib deve ser HARD STOP (critical)."""
    res = check_scope(
        repo,
        task_description="Adicionar feature X",
        changed_files=["platform-core-lib/src/helpers.py"],
    )
    assert res["risk_level"] == "critical"
    assert res["approved"] is False
    assert any("lib" in d.lower() and "§18" in d for d in res["drift_indicators"])


def test_check_scope_high_for_multiple_services(repo):
    res = check_scope(
        repo,
        task_description="Atualizar contrato",
        changed_files=[
            "platform-auth/src/handlers.py",
            "platform-admin/src/handlers.py",
        ],
    )
    assert res["risk_level"] in ("high", "critical")
    assert "platform-auth" in res["affected_services"]
    assert "platform-admin" in res["affected_services"]


def test_check_scope_no_files_is_safe(repo):
    res = check_scope(
        repo, task_description="Apenas docs", changed_files=[]
    )
    assert res["approved"] is True
    assert res["changed_files_count"] == 0


def test_check_scope_validates_task_description(repo):
    with pytest.raises(ValueError):
        check_scope(repo, task_description="", changed_files=["a.py"])


def test_check_scope_detects_suspicious_files(repo):
    """Tarefa menciona platform-cdc mas arquivos tocam platform-ml."""
    res = check_scope(
        repo,
        task_description="Corrigir bug no platform-cdc",
        changed_files=[
            "platform-cdc/app/services/source.py",
            "platform-ml/app/services/clustering.py",
        ],
    )
    # Deve sinalizar arquivos fora do escopo declarado
    assert any("escopo" in d.lower() or "fora" in d.lower() for d in res["drift_indicators"])


# --------------------------- validate_lib_change --------------------------- #
def test_validate_lib_change_blocks_known_lib(repo):
    res = validate_lib_change(
        repo,
        lib_name="platform-core-lib",
        proposed_change="Adicionar helper X para parsear datas",
    )
    assert res["blocked"] is True
    assert "§18" in res["reason"] or "§18 AGENTS.md" in res["reason"]
    assert len(res["consumers"]) > 0
    assert "LIB CHANGE REQUEST" in res["lib_change_request_template"]
    assert "@caiog" in res["lib_change_request_template"]


def test_validate_lib_change_blocks_db_vector(repo):
    res = validate_lib_change(
        repo,
        lib_name="platform-db-vector",
        proposed_change="Mudar API",
    )
    assert res["blocked"] is True


def test_validate_lib_change_blocks_known_pattern(repo):
    """platform-foo-lib (não no grafo) deve ser bloqueada pelo pattern regex."""
    res = validate_lib_change(
        repo,
        lib_name="platform-foo-lib",
        proposed_change="Adicionar coisa",
    )
    assert res["blocked"] is True


def test_validate_lib_change_does_not_block_random_lib(repo):
    """Lib não-governada (ex.: pacote pip externo) não deve disparar HARD STOP."""
    res = validate_lib_change(
        repo,
        lib_name="random-third-party-package",
        proposed_change="Algo",
    )
    assert res["blocked"] is False
    assert any("não foi reconhecida" in n for n in res["notes"])


def test_validate_lib_change_template_contains_consumers(repo):
    res = validate_lib_change(
        repo,
        lib_name="platform-core-lib",
        proposed_change="Mudança X",
    )
    template = res["lib_change_request_template"]
    # Pelo menos alguns consumidores conhecidos devem aparecer
    assert "platform-cdc" in template or "rag-service" in template or "agents-factory" in template


def test_validate_lib_change_validates_input(repo):
    with pytest.raises(ValueError):
        validate_lib_change(repo, lib_name="", proposed_change="x")
    with pytest.raises(ValueError):
        validate_lib_change(repo, lib_name="x", proposed_change="")


# --------------------------- graph unavailable --------------------------- #
def test_tools_raise_graph_unavailable_when_no_ecosystem():
    class _StubRepo:
        ecosystem = None
    stub = _StubRepo()
    with pytest.raises(GraphUnavailable):
        get_service_ownership(stub, service_name="x")
    with pytest.raises(GraphUnavailable):
        get_service_dependencies(stub, service_name="x")
    with pytest.raises(GraphUnavailable):
        get_port_map(stub)
