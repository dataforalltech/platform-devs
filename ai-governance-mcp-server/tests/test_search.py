"""Testes de search_governance_knowledge e do checklist final."""

from __future__ import annotations

import pytest

from src.tools.checklist_tool import get_final_response_template
from src.tools.repository_tool import search_governance_knowledge


def test_search_finds_fallback_doc(repo):
    res = search_governance_knowledge(repo, query="fallback silencioso")
    assert res["total"] > 0
    sources = {h["source"] for h in res["hits"]}
    assert "fallback.md" in sources or "AGENTS.md" in sources


def test_search_respects_limit(repo):
    res = search_governance_knowledge(repo, query="contrato", limit=2)
    assert len(res["hits"]) <= 2


def test_search_invalid_query(repo):
    with pytest.raises(ValueError):
        search_governance_knowledge(repo, query="")


def test_search_returns_related_rules(repo):
    res = search_governance_knowledge(repo, query="fallback")
    assert res["hits"], "deve haver pelo menos um hit"
    # ao menos um hit deve trazer related_rules (vem do mapping fixo)
    assert any(h["related_rules"] for h in res["hits"])


# --------------------------- final response template --------------------------- #
def test_final_response_template_default(repo):
    res = get_final_response_template(repo)
    keys = {s["key"] for s in res["sections"]}
    expected = {
        "what_changed",
        "why",
        "files_modified",
        "risks",
        "tests_executed",
        "tests_skipped_and_why",
        "impact_on_other_services",
        "pending_items",
    }
    assert expected.issubset(keys)
    assert res["template_markdown"].startswith("## Resposta final do agente")


def test_final_response_template_bugfix_adds_regression(repo):
    res = get_final_response_template(repo, task_type="bugfix")
    keys = {s["key"] for s in res["sections"]}
    assert "regression_test" in keys


def test_final_response_template_migration_adds_rollback(repo):
    res = get_final_response_template(repo, task_type="migration")
    keys = {s["key"] for s in res["sections"]}
    assert "rollback_plan" in keys
