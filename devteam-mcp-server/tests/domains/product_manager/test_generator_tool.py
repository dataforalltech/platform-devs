# Portado de `product-manager-mcp-server/tests/test_generator_tool.py` pelo fan-out de testes.
#
# O código de tool do agregador é byte-a-byte o do servidor legado; só o caminho
# de import muda. Gerado por `scripts/port_domain_tests.py` — reexecutar é
# idempotente. Editar aqui diverge da origem: corrija no legado e reexecute, ou
# aposente o legado (ver ROADMAP, fechar o strangler).

"""Unidade dos geradores determinísticos do product-manager (COMPUTE PURO — sem DB/LLM).

Estes testes NÃO tocam o MySQL: os geradores são funções puras ``spec -> dict``.
Cada gerador tem ao menos uma fixture-spec com asserts em marcadores-chave do output,
um guard de spec inválida, mais um teste global de DETERMINISMO (mesma spec 2x → igual)."""

from __future__ import annotations

import importlib

import pytest

_mod_tools_generator_tool = importlib.import_module("src.domains.product-manager.tools.generator_tool")
calculate_rice_score = _mod_tools_generator_tool.calculate_rice_score
generate_acceptance_criteria = _mod_tools_generator_tool.generate_acceptance_criteria
generate_handoff_to_architecture = _mod_tools_generator_tool.generate_handoff_to_architecture
generate_handoff_to_design = _mod_tools_generator_tool.generate_handoff_to_design
generate_handoff_to_engineering = _mod_tools_generator_tool.generate_handoff_to_engineering
generate_release_plan = _mod_tools_generator_tool.generate_release_plan

# ── Fixtures de spec (reaproveitadas nos testes de conteúdo e de determinismo) ─
RELEASE_SPEC = {
    "version": "2.1.0",
    "scope": ["Login SSO", "Dashboard v2"],
    "milestones": [
        {"name": "Beta", "date": "2026-03-01", "items": ["Feature flag", "Telemetria"]},
        {"name": "GA", "date": "2026-04-15"},
        "Post-launch review",
    ],
}
ACCEPTANCE_SPEC = {
    "story": {"role": "usuário admin", "goal": "exportar relatórios", "benefit": "auditar acessos"},
    "rules": [
        {
            "scenario": "Exportar CSV",
            "given": "estou logado",
            "when": "clico em exportar",
            "then": "baixo um CSV",
        },
        "o export respeita o filtro ativo",
    ],
}
RICE_SPEC = {"reach": 1000, "impact": 2, "confidence": 80, "effort": 4}
ARCH_SPEC = {"feature": "Busca full-text", "requirements": ["Latência < 200ms", "Indexação incremental"]}
DESIGN_SPEC = {"feature": "Onboarding", "flows": ["Sign-up", "Primeiro projeto"]}
ENG_SPEC = {"feature": "Webhooks", "specs": ["Retry exponencial", "Assinatura HMAC"]}


# ── 1. Release plan ───────────────────────────────────────────────────────────
def test_generate_release_plan_markers():
    out = generate_release_plan(RELEASE_SPEC)
    art = out["artifact"]
    assert out["kind"] == "release_plan"
    assert out["filename"] == "release-plan-v2.1.0.md"
    assert "# Release Plan — v2.1.0" in art
    assert "## Scope" in art and "- Login SSO" in art
    assert "## Milestones" in art
    assert "### Beta — 2026-03-01" in art
    assert "- Feature flag" in art
    assert "### Post-launch review" in art


def test_generate_release_plan_defaults_when_empty():
    art = generate_release_plan({"version": "0.1.0"})["artifact"]
    # sem scope/milestones → placeholders, sem inventar conteúdo de domínio.
    assert art.count("_A definir._") >= 2


def test_generate_release_plan_requires_version():
    assert generate_release_plan({"scope": ["x"]})["error"] == "missing_version"


# ── 2. Acceptance criteria (Gherkin) ──────────────────────────────────────────
def test_generate_acceptance_criteria_markers():
    out = generate_acceptance_criteria(ACCEPTANCE_SPEC)
    art = out["artifact"]
    assert out["kind"] == "acceptance_criteria"
    assert out["filename"] == "acceptance-criteria.feature"
    assert "Feature: exportar relatórios" in art
    assert "As a usuário admin" in art
    assert "So that auditar acessos" in art
    assert "Scenario: Exportar CSV" in art
    assert "Given estou logado" in art
    assert "When clico em exportar" in art
    assert "Then baixo um CSV" in art
    # regra em string → cai no Then com placeholders de Given/When
    assert "Then o export respeita o filtro ativo" in art


def test_generate_acceptance_criteria_defaults_when_no_rules():
    art = generate_acceptance_criteria({"story": {"role": "user", "goal": "fazer X"}})["artifact"]
    assert "Scenario: Rule 1" in art
    assert "_A definir._" in art


def test_generate_acceptance_criteria_requires_story():
    assert generate_acceptance_criteria({"story": {"role": "user"}})["error"] == "missing_story"


# ── 3. RICE score (cálculo determinístico) ────────────────────────────────────
def test_calculate_rice_score_computes_value():
    out = calculate_rice_score(RICE_SPEC)
    # RICE = 1000 * 2 * 80 / 4 = 40000
    assert out["kind"] == "rice_score"
    assert out["score"] == 40000
    assert "**40000**" in out["artifact"]
    assert "RICE = (Reach × Impact × Confidence) / Effort" in out["artifact"]


def test_calculate_rice_score_accepts_numeric_strings():
    out = calculate_rice_score({"reach": "500", "impact": "1", "confidence": "50", "effort": "5"})
    assert out["score"] == 5000


def test_calculate_rice_score_rejects_zero_effort():
    assert calculate_rice_score({"reach": 1, "impact": 1, "confidence": 1, "effort": 0})["error"] == (
        "invalid_effort"
    )


def test_calculate_rice_score_reports_missing_factors():
    out = calculate_rice_score({"reach": 1, "impact": 2})
    assert out["error"] == "missing_factor"
    assert set(out["missing"]) == {"confidence", "effort"}


# ── 4-6. Handoffs ─────────────────────────────────────────────────────────────
def test_generate_handoff_to_architecture_markers():
    out = generate_handoff_to_architecture(ARCH_SPEC)
    art = out["artifact"]
    assert out["kind"] == "handoff_architecture"
    assert out["filename"] == "handoff-architecture.md"
    assert "# Handoff → Architecture" in art
    assert "**Feature:** Busca full-text" in art
    assert "## Requirements" in art
    assert "- Latência < 200ms" in art


def test_generate_handoff_to_design_markers():
    out = generate_handoff_to_design(DESIGN_SPEC)
    art = out["artifact"]
    assert out["kind"] == "handoff_design"
    assert "# Handoff → Design" in art
    assert "## Flows" in art
    assert "- Sign-up" in art


def test_generate_handoff_to_engineering_markers():
    out = generate_handoff_to_engineering(ENG_SPEC)
    art = out["artifact"]
    assert out["kind"] == "handoff_engineering"
    assert "# Handoff → Engineering" in art
    assert "## Specs" in art
    assert "- Retry exponencial" in art


def test_generate_handoff_defaults_when_empty():
    art = generate_handoff_to_design({"feature": "X"})["artifact"]
    assert "_A definir._" in art


@pytest.mark.parametrize(
    "fn",
    [generate_handoff_to_architecture, generate_handoff_to_design, generate_handoff_to_engineering],
)
def test_generate_handoff_requires_feature(fn):
    assert fn({})["error"] == "missing_feature"


# ── Determinismo global (mesma spec chamada 2x → output idêntico) ─────────────
@pytest.mark.parametrize(
    "fn,spec",
    [
        (generate_release_plan, RELEASE_SPEC),
        (generate_acceptance_criteria, ACCEPTANCE_SPEC),
        (calculate_rice_score, RICE_SPEC),
        (generate_handoff_to_architecture, ARCH_SPEC),
        (generate_handoff_to_design, DESIGN_SPEC),
        (generate_handoff_to_engineering, ENG_SPEC),
    ],
)
def test_generators_are_deterministic(fn, spec):
    assert fn(dict(spec)) == fn(dict(spec))
