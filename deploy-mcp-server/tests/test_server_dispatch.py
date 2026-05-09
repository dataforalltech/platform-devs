"""Testes do servidor MCP: lista de tools registradas e dispatch."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.server.mcp_server import _TOOL_SCHEMAS, _dispatch

_EXPECTED_TOOLS = {
    # git
    "list_repos",
    "create_branch",
    "list_branches",
    "commit_files",
    # pr
    "create_pr",
    "get_pr",
    "merge_pr",
    "list_prs",
    # workflow
    "trigger_workflow",
    "list_workflow_runs",
    "get_workflow_run",
    "cancel_workflow_run",
    # deploy
    "deploy",
    "get_deploy_status",
    # pipeline
    "scaffold_pipeline",
    "get_pipeline_templates",
}


def test_all_tools_registered():
    """Verifica que exatamente os 16 tools esperados estão em _TOOL_SCHEMAS."""
    assert set(_TOOL_SCHEMAS.keys()) == _EXPECTED_TOOLS


def test_tool_count():
    assert len(_TOOL_SCHEMAS) == 16


def test_each_tool_has_description_and_schema():
    for name, meta in _TOOL_SCHEMAS.items():
        assert "description" in meta, f"{name}: falta 'description'"
        assert "schema" in meta, f"{name}: falta 'schema'"
        assert meta["description"].strip(), f"{name}: description vazia"
        schema = meta["schema"]
        assert schema.get("type") == "object", f"{name}: schema.type deve ser 'object'"
        assert "properties" in schema, f"{name}: schema.properties faltando"


def test_required_fields_are_in_properties():
    """required[] deve referenciar apenas campos definidos em properties."""
    for name, meta in _TOOL_SCHEMAS.items():
        schema = meta["schema"]
        props = set(schema.get("properties", {}).keys())
        required = set(schema.get("required", []))
        missing = required - props
        assert not missing, (
            f"{name}: required {missing} não estão em properties"
        )


def test_unknown_tool_raises_key_error(settings, client):
    """_dispatch deve levantar KeyError para tool desconhecida."""
    with pytest.raises(KeyError):
        _dispatch("non_existent_tool_xyz", {}, settings, client)


def test_get_pipeline_templates_dispatch(settings, client):
    """get_pipeline_templates não precisa de GitHub — retorna catálogo."""
    result = _dispatch("get_pipeline_templates", {}, settings, client)
    assert "templates" in result
    assert result["count"] == 6


def test_dispatch_list_repos(settings, client, mock_github):
    mock_org = MagicMock()
    mock_github.get_organization.return_value = mock_org
    mock_org.get_repos.return_value = []

    result = _dispatch("list_repos", {}, settings, client)

    assert "repos" in result
    assert result["count"] == 0


def test_dispatch_deploy_validation_error(settings, client):
    """deploy com environment inválido retorna erro — sem API call."""
    result = _dispatch(
        "deploy",
        {"service": "svc", "environment": "staging"},
        settings,
        client,
    )
    assert result["error"] == "ValidationError"
