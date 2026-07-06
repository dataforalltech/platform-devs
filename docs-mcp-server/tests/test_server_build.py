"""Tests for the server wiring: build_server(), the low-level MCP handlers, and
the FastAPI HTTP shim.

DocsStore is patched with the in-memory FakeDocsStore so building the server
never opens a psycopg2 pool, and get_settings' lru_cache is cleared so a fresh
DocsSettings is built from defaults.
"""

from __future__ import annotations

import pytest

import src.server.mcp_server as srv
from src.server.mcp_server import (
    _TOOL_SCHEMAS,
    SCOPE_FOR_TOOL,
    SCOPES_SUPPORTED,
    build_server,
)

from .conftest import FakeDocsStore


@pytest.fixture
def built(monkeypatch):
    monkeypatch.setattr(srv, "DocsStore", lambda settings: FakeDocsStore())
    srv.get_settings.cache_clear()
    server, settings, store, http_app = build_server()
    return server, settings, store, http_app


def test_build_server_returns_components(built):
    server, settings, store, http_app = built
    assert server is not None
    assert isinstance(store, FakeDocsStore)
    assert http_app.title == "Docs API"


async def test_http_list_tools_endpoint(built):
    _server, _settings, _store, http_app = built
    # Find the registered coroutine for /mcp/tools/list and call it.
    routes = {r.path: r for r in http_app.routes if hasattr(r, "path")}
    endpoint = routes["/mcp/tools/list"].endpoint
    body = await endpoint()
    tools = body["result"]["tools"]
    assert len(tools) == 14
    names = {t["name"] for t in tools}
    assert "scan_docs" in names


async def test_http_call_tool_endpoint(built):
    _server, _settings, _store, http_app = built
    routes = {r.path: r for r in http_app.routes if hasattr(r, "path")}
    endpoint = routes["/mcp/tools/call"].endpoint
    body = await endpoint({"params": {"name": "list_templates", "arguments": {}}})
    content = body["result"]["content"]
    assert content[0]["type"] == "text"
    assert "README" in content[0]["text"]


async def test_http_call_tool_unknown_tool(built):
    _server, _settings, _store, http_app = built
    routes = {r.path: r for r in http_app.routes if hasattr(r, "path")}
    endpoint = routes["/mcp/tools/call"].endpoint
    body = await endpoint({"params": {"name": "does_not_exist", "arguments": {}}})
    import json as _json

    payload = _json.loads(body["result"]["content"][0]["text"])
    assert payload["error"] == "unknown_tool"
    assert payload["tool"] == "does_not_exist"


async def test_http_call_tool_internal_error(built, monkeypatch):
    _server, _settings, _store, http_app = built
    # Force the dispatch to raise a non-KeyError so the internal_error branch runs.
    monkeypatch.setattr(
        srv, "_dispatch", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    routes = {r.path: r for r in http_app.routes if hasattr(r, "path")}
    endpoint = routes["/mcp/tools/call"].endpoint
    body = await endpoint({"params": {"name": "scan_docs", "arguments": {"repo_path": "/x"}}})
    import json as _json

    payload = _json.loads(body["result"]["content"][0]["text"])
    assert payload["error"] == "internal_error"
    assert "boom" in payload["details"]


async def test_health_endpoint(built):
    _server, _settings, _store, http_app = built
    routes = {r.path: r for r in http_app.routes if hasattr(r, "path")}
    endpoint = routes["/v1/health"].endpoint
    assert endpoint() == {"status": "ok", "service": "docs-mcp"}


def test_scope_map_is_complete():
    assert set(SCOPE_FOR_TOOL) == set(_TOOL_SCHEMAS)
    assert set(SCOPE_FOR_TOOL.values()) <= set(SCOPES_SUPPORTED)
