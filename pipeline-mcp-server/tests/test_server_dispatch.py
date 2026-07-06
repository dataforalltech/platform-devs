"""Testes do servidor MCP: schemas, escopos, dispatch e app HTTP."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from src.config.settings import PipelineSettings
from src.server import mcp_server
from src.server.mcp_server import (
    _TOOL_SCHEMAS,
    SCOPE_FOR_TOOL,
    SCOPES_SUPPORTED,
    _build_http_app,
    _dispatch,
    build_server,
)

from .conftest import FakePipelineStore

_EXPECTED_TOOLS = {
    # pipeline
    "register_pipeline",
    "get_pipeline",
    "list_pipeline",
    "promote_service",
    "approve_promotion",
    "watch_prs",
    "block_service",
    "rollback",
    # gates
    "add_gate_result",
    "get_gate_status",
    "clear_gates",
    # history / config
    "get_promotion_history",
    "get_pipeline_overview",
    "set_pipeline_config",
}


# ─────────────────────────────────────────────────────────────────────────── #
# Schemas + escopos                                                            #
# ─────────────────────────────────────────────────────────────────────────── #
def test_all_tools_registered():
    assert set(_TOOL_SCHEMAS.keys()) == _EXPECTED_TOOLS


def test_tool_count():
    assert len(_TOOL_SCHEMAS) == 14


def test_each_tool_has_description_and_schema():
    for name, meta in _TOOL_SCHEMAS.items():
        assert meta["description"].strip(), f"{name}: description vazia"
        schema = meta["schema"]
        assert schema["type"] == "object", f"{name}: schema.type deve ser object"
        assert "properties" in schema, f"{name}: falta properties"


def test_required_fields_in_properties():
    for name, meta in _TOOL_SCHEMAS.items():
        props = set(meta["schema"].get("properties", {}).keys())
        required = set(meta["schema"].get("required", []))
        assert required <= props, f"{name}: required {required - props} fora de properties"


def test_scope_map_covers_all_tools():
    """SCOPE_FOR_TOOL deve cobrir exatamente as tools (least privilege)."""
    assert set(SCOPE_FOR_TOOL.keys()) == set(_TOOL_SCHEMAS.keys())


def test_scopes_are_valid():
    assert set(SCOPE_FOR_TOOL.values()) <= set(SCOPES_SUPPORTED)


def test_read_tools_have_read_scope():
    for tool in (
        "get_pipeline",
        "list_pipeline",
        "get_gate_status",
        "get_promotion_history",
        "get_pipeline_overview",
    ):
        assert SCOPE_FOR_TOOL[tool] == "pipeline:read"


def test_write_tools_have_write_scope():
    for tool in (
        "promote_service",
        "approve_promotion",
        "rollback",
        "register_pipeline",
        "add_gate_result",
        "clear_gates",
        "block_service",
        "set_pipeline_config",
        "watch_prs",
    ):
        assert SCOPE_FOR_TOOL[tool] == "pipeline:write"


# ─────────────────────────────────────────────────────────────────────────── #
# _dispatch — roteia para cada tool                                            #
# ─────────────────────────────────────────────────────────────────────────── #
@pytest.fixture
def dispatch_store() -> FakePipelineStore:
    s = FakePipelineStore()
    s.register_pipeline("svc-a", "test-org/svc-a")
    return s


@pytest.fixture
def dispatch_settings() -> PipelineSettings:
    return PipelineSettings(github_token="", github_org="")


def test_dispatch_unknown_tool_raises(dispatch_store, dispatch_settings):
    with pytest.raises(KeyError):
        _dispatch("does_not_exist", {}, dispatch_settings, dispatch_store)


def test_dispatch_register_pipeline(dispatch_store, dispatch_settings):
    result = _dispatch(
        "register_pipeline",
        {"service": "new", "repo": "org/new"},
        dispatch_settings,
        dispatch_store,
    )
    assert result["action"] == "created"


def test_dispatch_register_uses_default_base_branch(dispatch_store, dispatch_settings):
    result = _dispatch(
        "register_pipeline", {"service": "n2", "repo": "org/n2"}, dispatch_settings, dispatch_store
    )
    assert result["pipeline"]["base_branch"] == "develop"


def test_dispatch_get_pipeline(dispatch_store, dispatch_settings):
    result = _dispatch("get_pipeline", {"service": "svc-a"}, dispatch_settings, dispatch_store)
    assert result["service"] == "svc-a"


def test_dispatch_list_pipeline(dispatch_store, dispatch_settings):
    result = _dispatch("list_pipeline", {}, dispatch_settings, dispatch_store)
    assert result["total"] == 1


def test_dispatch_promote_service_gates_fail(dispatch_store, dispatch_settings):
    result = _dispatch(
        "promote_service",
        {"service": "svc-a", "from_env": "dev", "to_env": "homol", "promoted_by": "u"},
        dispatch_settings,
        dispatch_store,
    )
    assert result["can_promote"] is False


def test_dispatch_approve_promotion_not_found(dispatch_store, dispatch_settings):
    result = _dispatch(
        "approve_promotion",
        {"promotion_id": 123, "approved_by": "a"},
        dispatch_settings,
        dispatch_store,
    )
    assert result["error"] == "not_found"


def test_dispatch_watch_prs_not_configured(dispatch_store, dispatch_settings):
    result = _dispatch("watch_prs", {}, dispatch_settings, dispatch_store)
    assert result["error"] == "github_not_configured"


def test_dispatch_block_service(dispatch_store, dispatch_settings):
    result = _dispatch(
        "block_service",
        {"service": "svc-a", "reason": "r", "blocked_by": "a"},
        dispatch_settings,
        dispatch_store,
    )
    assert result["blocked"] is True


def test_dispatch_rollback(dispatch_store, dispatch_settings):
    result = _dispatch(
        "rollback",
        {"service": "svc-a", "env": "prod", "to_version": "v1", "rolled_back_by": "ops"},
        dispatch_settings,
        dispatch_store,
    )
    assert result["rolled_back"] is True


def test_dispatch_add_gate_result(dispatch_store, dispatch_settings):
    result = _dispatch(
        "add_gate_result",
        {"service": "svc-a", "env": "dev", "gate_type": "qa_tests", "passed": True},
        dispatch_settings,
        dispatch_store,
    )
    assert result["gate_recorded"] is True


def test_dispatch_get_gate_status(dispatch_store, dispatch_settings):
    result = _dispatch(
        "get_gate_status",
        {"service": "svc-a", "env": "homol"},
        dispatch_settings,
        dispatch_store,
    )
    assert "can_promote" in result


def test_dispatch_clear_gates(dispatch_store, dispatch_settings):
    result = _dispatch(
        "clear_gates", {"service": "svc-a", "env": "dev"}, dispatch_settings, dispatch_store
    )
    assert result["cleared"] is True


def test_dispatch_get_promotion_history(dispatch_store, dispatch_settings):
    result = _dispatch("get_promotion_history", {}, dispatch_settings, dispatch_store)
    assert result["total"] == 0


def test_dispatch_get_promotion_history_default_limit(dispatch_store, dispatch_settings):
    result = _dispatch("get_promotion_history", {}, dispatch_settings, dispatch_store)
    assert result["limit"] == 20


def test_dispatch_get_pipeline_overview(dispatch_store, dispatch_settings):
    result = _dispatch("get_pipeline_overview", {}, dispatch_settings, dispatch_store)
    assert result["total_services"] == 1


def test_dispatch_set_pipeline_config(dispatch_store, dispatch_settings):
    result = _dispatch(
        "set_pipeline_config",
        {"service": "svc-a", "gates_required": {"homol": ["qa_tests"]}},
        dispatch_settings,
        dispatch_store,
    )
    assert result["updated"] is True


# ─────────────────────────────────────────────────────────────────────────── #
# App HTTP interno (_build_http_app)                                           #
# ─────────────────────────────────────────────────────────────────────────── #
class TestHttpApp:
    def _client(self, store):
        return TestClient(_build_http_app(store))

    def test_health_ok(self, dispatch_store):
        resp = self._client(dispatch_store).get("/v1/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["registered_pipelines"] == 1

    def test_health_degraded_on_store_error(self):
        class BrokenStore(FakePipelineStore):
            def list_pipelines(self, *a, **k):
                raise RuntimeError("db down")

        resp = self._client(BrokenStore()).get("/v1/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "degraded"

    def test_get_service_pipeline_found(self, dispatch_store):
        resp = self._client(dispatch_store).get("/v1/pipeline/svc-a")
        assert resp.status_code == 200
        assert resp.json()["service"] == "svc-a"

    def test_get_service_pipeline_404(self, dispatch_store):
        resp = self._client(dispatch_store).get("/v1/pipeline/ghost")
        assert resp.status_code == 404

    def test_root(self, dispatch_store):
        resp = self._client(dispatch_store).get("/")
        assert resp.status_code == 200
        assert resp.json()["service"] == "pipeline-mcp"


# ─────────────────────────────────────────────────────────────────────────── #
# build_server — Server MCP + endpoints /mcp/tools/*                           #
# ─────────────────────────────────────────────────────────────────────────── #
class TestBuildServer:
    @pytest.fixture
    def built(self, monkeypatch):
        """Constrói o server com PipelineStore/get_settings mockados (sem DB)."""
        fake = FakePipelineStore()
        fake.register_pipeline("svc-a", "test-org/svc-a")
        monkeypatch.setattr(mcp_server, "PipelineStore", lambda *a, **k: fake)
        monkeypatch.setattr(
            mcp_server, "get_settings", lambda: PipelineSettings(github_token="", github_org="")
        )
        server, store, settings, http_app = build_server()
        return server, store, settings, http_app

    def test_returns_components(self, built):
        server, store, settings, http_app = built
        assert server is not None
        assert isinstance(store, FakePipelineStore)
        assert settings.github_token == ""

    def test_http_list_tools_endpoint(self, built):
        _, _, _, http_app = built
        client = TestClient(http_app)
        resp = client.get("/mcp/tools/list")
        assert resp.status_code == 200
        tools = resp.json()["result"]["tools"]
        assert len(tools) == 14
        assert {t["name"] for t in tools} == _EXPECTED_TOOLS

    def test_http_call_tool_endpoint_ok(self, built):
        _, _, _, http_app = built
        client = TestClient(http_app)
        resp = client.post(
            "/mcp/tools/call",
            json={"params": {"name": "get_pipeline", "arguments": {"service": "svc-a"}}},
        )
        assert resp.status_code == 200
        content = resp.json()["result"]["content"]
        payload = json.loads(content[0]["text"])
        assert payload["service"] == "svc-a"

    def test_http_call_tool_unknown_tool(self, built):
        _, _, _, http_app = built
        client = TestClient(http_app)
        resp = client.post("/mcp/tools/call", json={"params": {"name": "nope", "arguments": {}}})
        payload = json.loads(resp.json()["result"]["content"][0]["text"])
        assert payload["error"] == "UnknownTool"

    def test_http_call_tool_internal_error(self, built, monkeypatch):
        _, _, _, http_app = built

        def _boom(*a, **k):
            raise RuntimeError("kaboom")

        monkeypatch.setattr(mcp_server, "_dispatch", _boom)
        client = TestClient(http_app)
        resp = client.post(
            "/mcp/tools/call", json={"params": {"name": "get_pipeline", "arguments": {}}}
        )
        payload = json.loads(resp.json()["result"]["content"][0]["text"])
        assert payload["error"] == "internal_error"
        assert "kaboom" in payload["details"]
