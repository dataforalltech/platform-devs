import json

import pytest

from src.server import mcp_server
from src.server.mcp_server import (
    _EXPECTED,
    _TOOL_SCHEMAS,
    SCOPE_FOR_TOOL,
    SCOPES_SUPPORTED,
    _build_http_app,
    _dispatch,
    build_server,
)

from .conftest import FakeAuditStore


def test_all_tools_registered():
    """Verifica que todos os tools estão registrados."""
    assert set(_TOOL_SCHEMAS.keys()) == _EXPECTED


def test_tool_count():
    """Verifica contagem exata de tools."""
    assert len(_TOOL_SCHEMAS) == 9


def test_each_schema_has_description_and_schema():
    """Verifica que cada schema tem description e schema."""
    for _name, meta in _TOOL_SCHEMAS.items():
        assert "description" in meta
        assert "schema" in meta
        assert meta["schema"]["type"] == "object"


def test_unknown_tool_raises_key_error(store, settings):
    """Verifica que tool desconhecido levanta erro."""
    with pytest.raises(KeyError):
        _dispatch("unknown_tool", {}, settings, store)


def test_dispatch_run_audit_missing_required_args(store, settings):
    """Testa run_audit sem args obrigatórios."""
    result = _dispatch("run_audit", {}, settings, store)
    assert "error" in result


def test_dispatch_invalid_arguments(store, settings):
    """Args extras/errados viram invalid_arguments (TypeError capturado)."""
    result = _dispatch("get_compliance_policy", {"env": "dev", "bogus": 1}, settings, store)
    assert result["error"] == "invalid_arguments"


@pytest.mark.parametrize(
    ("tool", "args"),
    [
        ("get_audit_status", {"service": "s", "env": "dev"}),
        ("get_compliance_policy", {"env": "dev"}),
        ("get_compliance_checklist", {"service": "s", "repo": "r", "env": "dev"}),
        ("get_audit_report", {}),
        ("list_audits", {}),
        ("set_service_criticality", {"service": "s", "criticality": "high", "updated_by": "u"}),
        ("get_audit_gate_result", {"service": "s", "env": "dev"}),
    ],
)
def test_dispatch_routes_each_tool(store, settings, tool, args):
    """_dispatch roteia cada tool para a função certa e devolve um dict."""
    result = _dispatch(tool, args, settings, store)
    assert isinstance(result, dict)
    assert "error" not in result or result["error"] not in {"unknown_tool", "invalid_arguments"}


def test_dispatch_submit_approval(store, settings):
    """Roteia submit_audit_approval (auditoria inexistente → NotFound)."""
    result = _dispatch(
        "submit_audit_approval",
        {"audit_id": "audit_x_dev", "approved_by": "a", "decision": "approved"},
        settings,
        store,
    )
    assert result["error"] == "NotFound"


def test_scope_maps_cover_all_tools():
    """Cada tool tem um scope mapeado; todos os scopes são suportados."""
    assert set(SCOPE_FOR_TOOL.keys()) == _EXPECTED
    assert set(SCOPE_FOR_TOOL.values()) <= set(SCOPES_SUPPORTED)


def test_build_http_app_health():
    """O app HTTP expõe /v1/health."""
    from fastapi.testclient import TestClient

    app = _build_http_app()
    client = TestClient(app)
    resp = client.get("/v1/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@pytest.fixture
def built_server(monkeypatch):
    """build_server() com AuditStore trocado pelo fake (sem PostgreSQL)."""
    monkeypatch.setattr(mcp_server, "AuditStore", FakeAuditStore)
    return build_server()


def test_build_server_returns_components(built_server):
    """build_server devolve (server, settings, store, http_app)."""
    server, settings, store, http_app = built_server
    assert server is not None
    assert isinstance(store, FakeAuditStore)
    # health continua acessível no http_app retornado
    from fastapi.testclient import TestClient

    resp = TestClient(http_app).get("/v1/health")
    assert resp.json()["service"] == "audit-mcp"


def test_http_app_mcp_tools_list_and_call(built_server):
    """As rotas HTTP /mcp/tools/list e /mcp/tools/call funcionam ponta a ponta."""
    from fastapi.testclient import TestClient

    _server, _settings, _store, http_app = built_server
    client = TestClient(http_app)

    listed = client.get("/mcp/tools/list")
    assert listed.status_code == 200
    tools = listed.json()["result"]["tools"]
    assert len(tools) == 9

    called = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "get_compliance_policy", "arguments": {"env": "dev"}}},
    )
    assert called.status_code == 200
    content = called.json()["result"]["content"]
    payload = json.loads(content[0]["text"])
    assert payload["env"] == "dev"


def test_http_app_call_unknown_tool(built_server):
    """Tool desconhecido via HTTP retorna erro unknown_tool no payload."""
    from fastapi.testclient import TestClient

    _server, _settings, _store, http_app = built_server
    client = TestClient(http_app)
    called = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "does_not_exist", "arguments": {}}},
    )
    payload = json.loads(called.json()["result"]["content"][0]["text"])
    assert payload["error"] == "unknown_tool"
