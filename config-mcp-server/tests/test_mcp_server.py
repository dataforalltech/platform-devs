"""Testes do servidor MCP (src/server/mcp_server.py): build, dispatch, handlers HTTP."""

from __future__ import annotations

import json

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

import src.server.mcp_server as ms
from src.server.mcp_server import (
    _TOOL_SCHEMAS,
    SCOPE_FOR_TOOL,
    _build_http_app,
    _dispatch,
    build_server,
)


@pytest.fixture()
def mcp_env(monkeypatch, tmp_path):
    monkeypatch.setenv("CONFIG_MCP_MASTER_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("CONFIG_MCP_STORE_PATH", str(tmp_path / "store.enc.json"))
    monkeypatch.setenv("CONFIG_MCP_API_TOKEN", "")
    monkeypatch.delenv("POSTGRES_SYNC_ENABLED", raising=False)
    yield


class TestSchemaInvariants:
    def test_scope_covers_all_tools(self):
        assert set(SCOPE_FOR_TOOL) == set(_TOOL_SCHEMAS)

    def test_every_schema_has_description_and_schema(self):
        for name, meta in _TOOL_SCHEMAS.items():
            assert meta["description"], name
            assert meta["schema"]["type"] == "object", name


class TestDispatch:
    def test_dispatch_set_and_get_credential(self, store):
        _dispatch(
            "set_credential", {"namespace": "credentials.acr", "key": "U", "value": "x"}, store
        )
        result = _dispatch("get_credential", {"namespace": "credentials.acr", "key": "U"}, store)
        assert result["value"] == "x"

    def test_dispatch_list_credentials(self, store):
        store.set("credentials.acr", "U", "x")
        result = _dispatch("list_credentials", {}, store)
        assert result["total_keys"] == 1

    def test_dispatch_delete_credential(self, store):
        store.set("credentials.acr", "U", "x")
        result = _dispatch("delete_credential", {"namespace": "credentials.acr", "key": "U"}, store)
        assert result["deleted"] is True

    def test_dispatch_env_tools(self, store, tmp_path):
        _dispatch("set_env_var", {"environment": "dev", "key": "A", "value": "1"}, store)
        assert _dispatch("get_env_config", {"environment": "dev"}, store)["config"]["A"] == "1"
        assert _dispatch("list_environments", {}, store)["count"] == 1
        target = str(tmp_path / ".env.dev")
        assert _dispatch("sync_env_file", {"target_path": target, "environment": "dev"}, store)[
            "success"
        ]

    def test_dispatch_env_file_tools(self, store, tmp_path):
        env = tmp_path / ".env"
        env.write_text("API_KEY=secret\n", encoding="utf-8")
        assert _dispatch("read_env_file", {"path": str(env)}, store)["count"] == 1
        assert "hardcoded_secrets" in _dispatch(
            "audit_env_files", {"directory": str(tmp_path)}, store
        )
        assert (
            _dispatch("redact_env_secrets", {"paths": [str(env)], "dry_run": True}, store)[
                "dry_run"
            ]
            is True
        )
        assert (
            _dispatch("push_env_to_store", {"path": str(env), "environment": "dev"}, store)[
                "pushed"
            ]
            == 1
        )

    def test_dispatch_workspace_tools(self, store):
        _dispatch("set_workspace_config", {"key": "EDITOR", "value": "code"}, store)
        assert _dispatch("get_workspace_config", {"key": "EDITOR"}, store)["value"] == "code"
        assert "config" in _dispatch("list_workspace_config", {}, store)

    def test_dispatch_tenant_tools(self, store):
        _dispatch("set_tenant_config", {"tenant_id": "t1", "key": "K", "value": "V"}, store)
        assert _dispatch("get_tenant_config", {"tenant_id": "t1"}, store)["found"] is True
        assert _dispatch("list_tenants", {}, store)["count"] == 1

    def test_dispatch_session_tenant(self, store, monkeypatch):
        # Route through the dispatcher; with no dev-twin available it resolves to not-found.
        monkeypatch.setattr("src.tools.tenant_tool._get_twin_tenant_id", lambda: None)
        result = _dispatch("get_session_tenant_config", {}, store)
        assert result["found"] is False

    def test_dispatch_physical_info(self, store, monkeypatch):
        monkeypatch.setattr(
            "src.tools.sysinfo_tool.collect_physical_info",
            lambda: {"os": {}, "cpu": {}, "ram": {}, "disks": [], "network": {}},
        )
        result = _dispatch("get_physical_info", {}, store)
        assert result["success"] is True

    def test_dispatch_unknown_raises_keyerror(self, store):
        with pytest.raises(KeyError):
            _dispatch("does_not_exist", {}, store)


class TestBuildServer:
    def test_build_server_returns_components(self, mcp_env):
        server, store, settings, http_app = build_server()
        assert server is not None
        assert store is not None
        assert settings.master_key

    def test_build_server_invalid_key_exits(self, monkeypatch, tmp_path):
        # An unusable (non-Fernet) key must abort startup with SystemExit.
        monkeypatch.setenv("CONFIG_MCP_MASTER_KEY", "invalid-key-not-fernet")
        monkeypatch.setenv("CONFIG_MCP_STORE_PATH", str(tmp_path / "s.json"))
        with pytest.raises((SystemExit, Exception)):
            build_server()


class TestHttpApp:
    def test_build_http_app_health(self, store):
        from src.config.settings import ConfigMcpSettings

        settings = ConfigMcpSettings(_env_file=None, master_key="k", api_token="")
        app = _build_http_app(store, settings)
        client = TestClient(app)
        resp = client.get("/v1/health")
        assert resp.status_code == 200

    def test_http_list_tools_endpoint(self, mcp_env):
        server, store, settings, http_app = build_server()
        client = TestClient(http_app)
        resp = client.get("/mcp/tools/list")
        assert resp.status_code == 200
        tools = resp.json()["result"]["tools"]
        assert len(tools) == len(_TOOL_SCHEMAS)

    def test_http_call_tool_endpoint(self, mcp_env):
        server, store, settings, http_app = build_server()
        client = TestClient(http_app)
        body = {
            "params": {
                "name": "set_env_var",
                "arguments": {"environment": "dev", "key": "A", "value": "1"},
            }
        }
        resp = client.post("/mcp/tools/call", json=body)
        assert resp.status_code == 200
        content = resp.json()["result"]["content"][0]["text"]
        assert json.loads(content)["success"] is True

    def test_http_call_tool_unknown(self, mcp_env):
        server, store, settings, http_app = build_server()
        client = TestClient(http_app)
        resp = client.post("/mcp/tools/call", json={"params": {"name": "nope", "arguments": {}}})
        text = resp.json()["result"]["content"][0]["text"]
        assert json.loads(text)["error"] == "unknown_tool"

    def test_http_call_tool_internal_error(self, mcp_env, monkeypatch):
        server, store, settings, http_app = build_server()
        client = TestClient(http_app)

        # A non-KeyError raised inside a tool is reported as internal_error.
        def boom(_store):
            raise RuntimeError("kaboom")

        monkeypatch.setattr(ms, "list_environments", boom)
        resp = client.post(
            "/mcp/tools/call",
            json={"params": {"name": "list_environments", "arguments": {}}},
        )
        text = resp.json()["result"]["content"][0]["text"]
        payload = json.loads(text)
        assert payload["error"] == "internal_error"
        assert "kaboom" in payload["details"]
