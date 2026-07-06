"""Testes do servidor MCP (build_server, list_tools, call_tool, dispatch, HTTP wrappers).

Herméticos: o pool psycopg2 e get_settings são substituídos por fakes; nenhum
banco real nem transporte HTTP externo é tocado.
"""

from __future__ import annotations

import json

import psycopg2.pool
import pytest

from src.config.settings import DevTwinSettings
from src.knowledge.session import SessionManager
from src.server import mcp_server
from tests.conftest import _FakePool


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    """Pool in-memory + settings determinísticas + sessão limpa."""
    monkeypatch.setattr(psycopg2.pool, "ThreadedConnectionPool", _FakePool)
    settings = DevTwinSettings(
        pg_host="fake",
        pg_db="fake",
        pg_user="fake",
        pg_password="fake",
        admin_token="admin-secret",
        api_token="",
    )
    monkeypatch.setattr(mcp_server, "get_settings", lambda: settings)
    SessionManager.clear()
    yield
    SessionManager.clear()


@pytest.fixture()
def built():
    server, store, settings, http_app = mcp_server.build_server()
    return server, store, settings, http_app


class TestBuildServer:
    def test_returns_components(self, built):
        server, store, settings, http_app = built
        assert server is not None
        assert store is not None
        assert settings.admin_token == "admin-secret"
        assert http_app.title == "dev-twin-mcp API"


class TestListTools:
    def test_lists_nine_tools(self):
        # o handler é registrado internamente; usamos o schema declarado
        tools = mcp_server._TOOL_SCHEMAS
        assert len(tools) == 9
        assert set(tools) == {
            "authenticate",
            "whoami",
            "get_twin_context",
            "refresh_context",
            "context_status",
            "register_token",
            "revoke_token",
            "rotate_token",
            "list_tokens",
        }

    def test_scope_map_covers_all_tools(self):
        assert set(mcp_server.SCOPE_FOR_TOOL) == set(mcp_server._TOOL_SCHEMAS)
        assert set(mcp_server.SCOPE_FOR_TOOL.values()) <= set(mcp_server.SCOPES_SUPPORTED)


class TestDispatch:
    def test_dispatch_authenticate_flow(self, built):
        _server, store, settings, _http = built
        reg = store.register(name="Alice", email="alice@test.com")
        result = mcp_server._dispatch("authenticate", {"token": reg["token"]}, store, settings)
        assert result["authenticated"] is True
        assert result["name"] == "Alice"

    def test_dispatch_whoami_and_context(self, built):
        _server, store, settings, _http = built
        reg = store.register(name="Bob", email="bob@test.com")
        mcp_server._dispatch("authenticate", {"token": reg["token"]}, store, settings)
        who = mcp_server._dispatch("whoami", {}, store, settings)
        assert who["name"] == "Bob"
        ctx = mcp_server._dispatch("get_twin_context", {}, store, settings)
        assert ctx["authenticated"] is True
        status = mcp_server._dispatch("context_status", {}, store, settings)
        assert status["authenticated"] is True
        refreshed = mcp_server._dispatch("refresh_context", {}, store, settings)
        assert refreshed["success"] is True

    def test_dispatch_admin_register_revoke_rotate_list(self, built):
        _server, store, settings, _http = built
        reg = mcp_server._dispatch(
            "register_token",
            {"admin_token": "admin-secret", "name": "Carol", "email": "carol@test.com"},
            store,
            settings,
        )
        assert reg["success"] is True
        listed = mcp_server._dispatch(
            "list_tokens", {"admin_token": "admin-secret"}, store, settings
        )
        assert listed["count"] >= 1
        rot = mcp_server._dispatch(
            "rotate_token",
            {"admin_token": "admin-secret", "identifier": reg["user_id"]},
            store,
            settings,
        )
        assert rot["success"] is True
        rev = mcp_server._dispatch(
            "revoke_token",
            {"admin_token": "admin-secret", "identifier": rot["user_id"]},
            store,
            settings,
        )
        assert rev["success"] is True

    def test_dispatch_unknown_tool_raises(self, built):
        _server, store, settings, _http = built
        with pytest.raises(KeyError):
            mcp_server._dispatch("does_not_exist", {}, store, settings)


class TestCallToolHandler:
    """Exercita o handler async call_tool via os endpoints HTTP montados."""

    def _client(self, http_app):
        from fastapi.testclient import TestClient

        return TestClient(http_app)

    def test_http_list_tools(self, built):
        http_app = built[3]
        client = self._client(http_app)
        resp = client.get("/mcp/tools/list")
        assert resp.status_code == 200
        tools = resp.json()["result"]["tools"]
        assert len(tools) == 9

    def test_http_call_tool_authenticate(self, built):
        _server, store, _settings, http_app = built
        reg = store.register(name="Dave", email="dave@test.com")
        client = self._client(http_app)
        resp = client.post(
            "/mcp/tools/call",
            json={"params": {"name": "authenticate", "arguments": {"token": reg["token"]}}},
        )
        assert resp.status_code == 200
        content = resp.json()["result"]["content"]
        payload = json.loads(content[0]["text"])
        assert payload["authenticated"] is True
        assert payload["name"] == "Dave"

    def test_http_call_tool_unknown(self, built):
        http_app = built[3]
        client = self._client(http_app)
        resp = client.post(
            "/mcp/tools/call",
            json={"params": {"name": "nope", "arguments": {}}},
        )
        assert resp.status_code == 200
        payload = json.loads(resp.json()["result"]["content"][0]["text"])
        assert payload["error"] == "unknown_tool"

    def test_http_call_tool_internal_error(self, built):
        """Erro inesperado no dispatch (store falha) → payload internal_error."""
        _server, store, _settings, http_app = built

        def _boom(_token):
            raise ValueError("db exploded")

        store.validate = _boom  # type: ignore[method-assign]
        client = self._client(http_app)
        resp = client.post(
            "/mcp/tools/call",
            json={"params": {"name": "authenticate", "arguments": {"token": "x"}}},
        )
        assert resp.status_code == 200
        payload = json.loads(resp.json()["result"]["content"][0]["text"])
        assert payload["error"] == "internal_error"


class TestBuildApp:
    def test_build_app_uses_shared_auth(self, monkeypatch, built):
        """build_app delega a shared.mcp_auth.mount_lowlevel_streamable_http."""
        import sys
        import types

        sentinel = object()
        captured = {}

        fake_mod = types.ModuleType("shared.mcp_auth")

        def _mount(server, **kwargs):
            captured["server"] = server
            captured["kwargs"] = kwargs
            return sentinel

        fake_mod.mount_lowlevel_streamable_http = _mount
        shared_pkg = types.ModuleType("shared")
        monkeypatch.setitem(sys.modules, "shared", shared_pkg)
        monkeypatch.setitem(sys.modules, "shared.mcp_auth", fake_mod)

        app = mcp_server.build_app()
        assert app is sentinel
        assert captured["kwargs"]["scopes_supported"] == mcp_server.SCOPES_SUPPORTED
        assert captured["kwargs"]["scope_for_tool"] == mcp_server.SCOPE_FOR_TOOL


class TestMain:
    def test_main_runs_uvicorn(self, monkeypatch):
        calls = {}

        def fake_run(app, **kwargs):
            calls["app"] = app
            calls["kwargs"] = kwargs

        import uvicorn

        monkeypatch.setattr(uvicorn, "run", fake_run)
        monkeypatch.setattr(mcp_server, "build_app", lambda: "APP")
        mcp_server.main()
        assert calls["app"] == "APP"
        assert calls["kwargs"]["port"] == 7101
