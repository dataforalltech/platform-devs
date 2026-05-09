"""Testes de get_agent_guidelines e get_pre_execution_checklist."""

from __future__ import annotations

import pytest

from src.tools.guidelines_tool import (
    get_agent_guidelines,
    get_pre_execution_checklist,
)


def test_universal_rules_always_returned(repo):
    res = get_agent_guidelines(repo)
    assert res["repository_name"] is None
    assert res["task_type"] is None
    assert res["layer"] is None
    assert any("AGENTS.md" in r for r in res["mandatory_rules"])
    assert any("silencioso" in f.lower() for f in res["forbidden_actions"])
    assert "AGENTS.md" in res["references"]


def test_layer_specific_rules_added(repo):
    res = get_agent_guidelines(repo, layer="integrations")
    assert res["layer"] == "integrations"
    assert any(
        "timeout" in r.lower() or "fallback" in r.lower()
        for r in res["mandatory_rules"]
    )
    assert "integrations.md" in res["references"]


def test_invalid_layer_raises(repo):
    with pytest.raises(ValueError):
        get_agent_guidelines(repo, layer="unknown")


def test_bugfix_requires_regression_test(repo):
    res = get_agent_guidelines(repo, task_type="bugfix")
    assert any("regress" in r.lower() for r in res["mandatory_rules"])


def test_pre_checklist_requires_repo_and_description(repo):
    with pytest.raises(ValueError):
        get_pre_execution_checklist(repo, repository_name="", task_description="x")
    with pytest.raises(ValueError):
        get_pre_execution_checklist(repo, repository_name="x", task_description="")


def test_pre_checklist_layer_specific(repo):
    res = get_pre_execution_checklist(
        repo,
        repository_name="orders-service",
        task_description="Adicionar campo X em /orders",
        layer="database",
    )
    assert res["layer"] == "database"
    assert "database.md" in res["docs_to_read"]
    assert any("reversível" in q.lower() for q in res["questions_to_answer"])


def test_pre_checklist_detects_fallback_keyword(repo):
    res = get_pre_execution_checklist(
        repo,
        repository_name="x",
        task_description="adicionar fallback para serviço de email",
    )
    assert "fallback.md" in res["docs_to_read"]
    assert any("silencio" in q.lower() for q in res["questions_to_answer"])
