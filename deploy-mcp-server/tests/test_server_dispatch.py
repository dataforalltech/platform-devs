"""Testes do servidor MCP: lista de tools registradas e dispatch."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest

from src.server import mcp_server
from src.server.mcp_server import (
    _TOOL_SCHEMAS,
    SCOPE_FOR_TOOL,
    _dispatch,
)

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
    # acr
    "setup_repo",
    "acr_build",
    "list_acr_images",
    # healthcheck
    "ensure_all_repos_healthy",
    # local workspace
    "get_repos_root",
    "set_repos_root",
    "list_local_repos",
    "clone_repo",
}


def test_all_tools_registered():
    """Verifica que exatamente os 24 tools esperados estão em _TOOL_SCHEMAS."""
    assert set(_TOOL_SCHEMAS.keys()) == _EXPECTED_TOOLS


def test_tool_count():
    assert len(_TOOL_SCHEMAS) == 24


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
        assert not missing, f"{name}: required {missing} não estão em properties"


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


# ─────────────────────────────────────────────────────────────────────────── #
# Consistência scopes × schemas                                                #
# ─────────────────────────────────────────────────────────────────────────── #
def test_every_tool_has_a_scope():
    assert set(SCOPE_FOR_TOOL.keys()) == set(_TOOL_SCHEMAS.keys())


def test_scopes_are_valid():
    assert set(SCOPE_FOR_TOOL.values()) <= {"deploy:read", "deploy:write"}


# ─────────────────────────────────────────────────────────────────────────── #
# _dispatch — cobre cada braço chamando a tool subjacente (stubada)            #
# ─────────────────────────────────────────────────────────────────────────── #
# Mapa: tool → (nome do símbolo no módulo, args mínimos)
_DISPATCH_CASES = {
    "create_branch": ("create_branch", {"repo": "r", "branch": "b"}),
    "list_branches": ("list_branches", {"repo": "r"}),
    "commit_files": ("commit_files", {"repo": "r", "branch": "b", "message": "m", "files": []}),
    "create_pr": ("create_pr", {"repo": "r", "title": "t", "head": "h"}),
    "get_pr": ("get_pr", {"repo": "r", "pr_number": 1}),
    "merge_pr": ("merge_pr", {"repo": "r", "pr_number": 1}),
    "list_prs": ("list_prs", {"repo": "r"}),
    "trigger_workflow": ("trigger_workflow", {"repo": "r", "workflow_id": "w", "ref": "x"}),
    "list_workflow_runs": ("list_workflow_runs", {"repo": "r"}),
    "get_workflow_run": ("get_workflow_run", {"repo": "r", "run_id": 1}),
    "cancel_workflow_run": ("cancel_workflow_run", {"repo": "r", "run_id": 1}),
    "deploy": ("deploy", {"service": "s", "environment": "dev"}),
    "get_deploy_status": ("get_deploy_status", {"service": "s", "environment": "dev"}),
    "scaffold_pipeline": ("scaffold_pipeline", {"repo": "r"}),
    "setup_repo": ("setup_repo", {"repo": "r", "image_name": "i"}),
    "acr_build": ("acr_build", {"repo_path": "/p", "image_name": "i"}),
    "list_acr_images": ("list_acr_images", {"service_name": "s"}),
    "ensure_all_repos_healthy": ("ensure_all_repos_healthy", {}),
    "get_repos_root": ("get_repos_root", {}),
    "set_repos_root": ("set_repos_root", {"path": "/p"}),
    "list_local_repos": ("list_local_repos", {}),
    "clone_repo": ("clone_repo", {"repo": "r"}),
}


@pytest.mark.parametrize("tool_name", sorted(_DISPATCH_CASES.keys()))
def test_dispatch_routes_to_correct_tool(tool_name, settings, client, monkeypatch):
    symbol, args = _DISPATCH_CASES[tool_name]
    sentinel = {"routed": tool_name}
    stub = MagicMock(return_value=sentinel)
    monkeypatch.setattr(mcp_server, symbol, stub)

    result = _dispatch(tool_name, args, settings, client)

    assert result == sentinel
    stub.assert_called_once()


# ─────────────────────────────────────────────────────────────────────────── #
# build_server + handlers list_tools / call_tool                               #
# ─────────────────────────────────────────────────────────────────────────── #
def _handlers(settings, monkeypatch):
    """Constrói o server e devolve os handlers async de list_tools/call_tool."""
    from mcp.types import CallToolRequest, ListToolsRequest

    monkeypatch.setattr(mcp_server, "get_settings", lambda: settings)
    server, _s, _c = mcp_server.build_server()
    return server.request_handlers[ListToolsRequest], server.request_handlers[CallToolRequest]


async def test_list_tools_handler_returns_all_24(settings, mock_github, monkeypatch):
    from mcp.types import ListToolsRequest

    list_tools, _ = _handlers(settings, monkeypatch)
    res = await list_tools(ListToolsRequest(method="tools/list"))
    tools = res.root.tools
    assert len(tools) == 24
    assert {t.name for t in tools} == _EXPECTED_TOOLS


async def test_call_tool_handler_serializes_payload(settings, mock_github, monkeypatch):
    from mcp.types import CallToolRequest, CallToolRequestParams

    _, call_tool = _handlers(settings, monkeypatch)
    req = CallToolRequest(
        method="tools/call",
        params=CallToolRequestParams(name="get_pipeline_templates", arguments={}),
    )
    res = await call_tool(req)
    text = res.root.content[0].text
    assert "templates" in text


async def test_call_tool_handler_unknown_tool(settings, mock_github, monkeypatch):
    from mcp.types import CallToolRequest, CallToolRequestParams

    _, call_tool = _handlers(settings, monkeypatch)
    req = CallToolRequest(
        method="tools/call",
        params=CallToolRequestParams(name="does_not_exist", arguments={}),
    )
    res = await call_tool(req)
    assert "unknown_tool" in res.root.content[0].text


async def test_call_tool_handler_internal_error(settings, mock_github, monkeypatch):
    """Exceção genérica dentro do dispatch vira payload internal_error (não propaga)."""
    from mcp.types import CallToolRequest, CallToolRequestParams

    _, call_tool = _handlers(settings, monkeypatch)
    monkeypatch.setattr(mcp_server, "_dispatch", MagicMock(side_effect=RuntimeError("kaboom")))
    req = CallToolRequest(
        method="tools/call",
        params=CallToolRequestParams(name="get_pipeline_templates", arguments={}),
    )
    res = await call_tool(req)
    text = res.root.content[0].text
    assert "internal_error" in text
    assert "kaboom" in text


# ─────────────────────────────────────────────────────────────────────────── #
# build_app — transporte Streamable HTTP (shared.mcp_auth mockado)             #
# ─────────────────────────────────────────────────────────────────────────── #
def test_build_app_wires_scopes(settings, mock_github, monkeypatch):
    monkeypatch.setattr(mcp_server, "get_settings", lambda: settings)

    captured = {}

    def fake_mount(server, **kwargs):
        captured.update(kwargs)
        captured["server"] = server
        return "ASGI_APP"

    fake_shared = MagicMock()
    fake_shared.mount_lowlevel_streamable_http = fake_mount
    monkeypatch.setitem(sys.modules, "shared", MagicMock())
    monkeypatch.setitem(sys.modules, "shared.mcp_auth", fake_shared)

    app = mcp_server.build_app()

    assert app == "ASGI_APP"
    assert captured["scope_for_tool"] == SCOPE_FOR_TOOL
    assert captured["scopes_supported"] == ["deploy:read", "deploy:write"]
    assert captured["server"] is not None


def test_dispatch_deploy_validation_error(settings, client):
    """deploy com environment inválido retorna erro — sem API call."""
    result = _dispatch(
        "deploy",
        {"service": "svc", "environment": "staging"},
        settings,
        client,
    )
    assert result["error"] == "ValidationError"
