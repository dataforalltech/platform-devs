# Portado de `product-owner-mcp-server/tests/test_generator_tool.py` pelo fan-out de testes.
#
# O código de tool do agregador é byte-a-byte o do servidor legado; só o caminho
# de import muda. Gerado por `scripts/port_domain_tests.py` — reexecutar é
# idempotente. Editar aqui diverge da origem: corrija no legado e reexecute, ou
# aposente o legado (ver ROADMAP, fechar o strangler).

"""Unidade dos geradores determinísticos de PO (COMPUTE PURO — sem DB, sem LLM).

Estes testes NÃO tocam o MySQL: os geradores são funções puras ``spec -> dict``.
Cada gerador tem ao menos uma fixture-spec com asserts em marcadores-chave do output,
um guard de spec inválida, mais um teste global de DETERMINISMO (mesma spec chamada
2x → output idêntico)."""

from __future__ import annotations

import importlib

import pytest

_mod_tools_generator_tool = importlib.import_module("src.domains.product-owner.tools.generator_tool")
generate_epic = _mod_tools_generator_tool.generate_epic
generate_feature_breakdown = _mod_tools_generator_tool.generate_feature_breakdown
generate_homologation_checklist = _mod_tools_generator_tool.generate_homologation_checklist
generate_jira_tasks = _mod_tools_generator_tool.generate_jira_tasks
generate_release_notes = _mod_tools_generator_tool.generate_release_notes
generate_user_stories = _mod_tools_generator_tool.generate_user_stories

# ── Fixtures de spec (reaproveitadas nos testes de conteúdo e de determinismo) ─
EPIC_SPEC = {
    "title": "Checkout Rápido",
    "goal": "Reduzir o abandono de carrinho",
    "stories": [
        "Como cliente quero pagar com um clique",
        {"title": "Como cliente quero salvar cartão"},
    ],
}
FEATURE_BREAKDOWN_SPEC = {
    "feature": "Autenticação SSO",
    "parts": [
        {"name": "Backend", "items": ["Endpoint OAuth", "Validação de token"]},
        "Frontend",
    ],
}
JIRA_TASKS_SPEC = {
    "project": "PO",
    "breakdown": [
        "Implementar endpoint OAuth",
        {"summary": "Tela de login", "type": "Story", "description": "UI de login SSO"},
    ],
}
RELEASE_NOTES_SPEC = {
    "version": "1.2.0",
    "changes": [
        {"type": "feature", "desc": "Login com SSO"},
        {"type": "fix", "desc": "Corrige timeout no checkout"},
        {"type": "feature", "desc": "Exportar relatório"},
    ],
}
USER_STORY_SPEC = {
    "role": "gestor de produto",
    "goal": "acompanhar o backlog priorizado",
    "benefit": "tomar decisões baseadas em valor",
    "criteria": ["Backlog ordenado por score", "Filtro por status"],
}
CHECKLIST_SPEC = {
    "title": "Release 1.2",
    "items": ["Smoke test do login", {"label": "Validar métricas"}, "Regressão de checkout"],
}


# ── 1. Épico ──────────────────────────────────────────────────────────────────
def test_generate_epic_markers():
    out = generate_epic(EPIC_SPEC)
    art = out["artifact"]
    assert out["kind"] == "epic"
    assert out["filename"] == "epic-checkout-rapido.md"
    assert "# Épico: Checkout Rápido" in art
    assert "## Objetivo" in art
    assert "Reduzir o abandono de carrinho" in art
    assert "## User Stories" in art
    assert "- [ ] Como cliente quero pagar com um clique" in art
    assert "- [ ] Como cliente quero salvar cartão" in art


def test_generate_epic_requires_title():
    assert generate_epic({"goal": "x"})["error"] == "missing_title"


# ── 2. Breakdown de feature ───────────────────────────────────────────────────
def test_generate_feature_breakdown_markers():
    out = generate_feature_breakdown(FEATURE_BREAKDOWN_SPEC)
    art = out["artifact"]
    assert out["kind"] == "feature_breakdown"
    assert out["filename"] == "autenticacao-sso-breakdown.md"
    assert "# Breakdown da Feature: Autenticação SSO" in art
    assert "## Backend" in art
    assert "- Endpoint OAuth" in art
    assert "- Validação de token" in art
    assert "## Frontend" in art


def test_generate_feature_breakdown_requires_feature():
    assert generate_feature_breakdown({"parts": []})["error"] == "missing_feature"


# ── 3. Tasks de Jira ──────────────────────────────────────────────────────────
def test_generate_jira_tasks_markers():
    out = generate_jira_tasks(JIRA_TASKS_SPEC)
    art = out["artifact"]
    assert out["kind"] == "jira_tasks"
    assert isinstance(art, dict)
    tasks = art["tasks"]
    assert [t["key"] for t in tasks] == ["PO-1", "PO-2"]
    assert tasks[0]["summary"] == "Implementar endpoint OAuth"
    assert tasks[0]["type"] == "Task"
    assert tasks[1]["type"] == "Story"
    assert tasks[1]["description"] == "UI de login SSO"


def test_generate_jira_tasks_requires_breakdown():
    assert generate_jira_tasks({"breakdown": []})["error"] == "missing_breakdown"


# ── 4. Release notes ──────────────────────────────────────────────────────────
def test_generate_release_notes_markers():
    out = generate_release_notes(RELEASE_NOTES_SPEC)
    art = out["artifact"]
    assert out["kind"] == "release_notes"
    assert out["filename"] == "release-1-2-0.md"
    assert "# Release 1.2.0" in art
    assert "## Funcionalidades" in art
    assert "## Correções" in art
    assert "- Login com SSO" in art
    assert "- Exportar relatório" in art
    assert "- Corrige timeout no checkout" in art
    # agrupamento por tipo em ordem estável: 'feature' antes de 'fix'
    assert art.index("## Funcionalidades") < art.index("## Correções")


def test_generate_release_notes_requires_version():
    assert generate_release_notes({"changes": []})["error"] == "missing_version"


# ── 5. User story ─────────────────────────────────────────────────────────────
def test_generate_user_stories_markers():
    out = generate_user_stories(USER_STORY_SPEC)
    art = out["artifact"]
    assert out["kind"] == "user_story"
    assert out["filename"] == "user-story-gestor-de-produto.md"
    assert (
        "**Como** gestor de produto, **quero** acompanhar o backlog priorizado, "
        "**para** tomar decisões baseadas em valor." in art
    )
    assert "### Critérios de Aceite" in art
    assert "- [ ] Backlog ordenado por score" in art


def test_generate_user_stories_requires_role_and_goal():
    assert generate_user_stories({"goal": "x"})["error"] == "missing_role"
    assert generate_user_stories({"role": "x"})["error"] == "missing_goal"


# ── 6. Checklist de homologação ───────────────────────────────────────────────
def test_generate_homologation_checklist_markers():
    out = generate_homologation_checklist(CHECKLIST_SPEC)
    art = out["artifact"]
    assert out["kind"] == "homologation_checklist"
    assert out["filename"] == "release-1-2-checklist.md"
    assert "# Checklist de Release 1.2" in art
    assert "- [ ] Smoke test do login" in art
    assert "- [ ] Validar métricas" in art
    assert "- [ ] Regressão de checkout" in art


def test_generate_homologation_checklist_requires_items():
    assert generate_homologation_checklist({"items": []})["error"] == "missing_items"


# ── Determinismo global (mesma spec chamada 2x → output idêntico) ─────────────
@pytest.mark.parametrize(
    "fn,spec",
    [
        (generate_epic, EPIC_SPEC),
        (generate_feature_breakdown, FEATURE_BREAKDOWN_SPEC),
        (generate_jira_tasks, JIRA_TASKS_SPEC),
        (generate_release_notes, RELEASE_NOTES_SPEC),
        (generate_user_stories, USER_STORY_SPEC),
        (generate_homologation_checklist, CHECKLIST_SPEC),
    ],
)
def test_generators_are_deterministic(fn, spec):
    assert fn(dict(spec)) == fn(dict(spec))


def test_release_notes_grouping_is_stable_regardless_of_input_order():
    # mesma composição, ordens de inserção de tipos diferentes → mesmo output.
    a = generate_release_notes(
        {"version": "1.0.0", "changes": [{"type": "fix", "desc": "b"}, {"type": "feat", "desc": "a"}]}
    )
    b = generate_release_notes(
        {"version": "1.0.0", "changes": [{"type": "feat", "desc": "a"}, {"type": "fix", "desc": "b"}]}
    )
    assert a == b
