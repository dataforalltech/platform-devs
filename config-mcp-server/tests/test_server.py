"""Sidecar HTTP governado (STD-MCP-001 / STD-SEC-006): catálogo com policy, verificação
RS256 real do inner token, denylist e dispatch storeless — sem tocar o MySQL.

Estes testes exercitam a borda gateway (token/tenant/policy) e as tools storeless
(status/get_physical_info), que não abrem sessão de tenant. O caminho DB-backed é
coberto por test_store.py / test_tools.py (MySQL real)."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from src.config.settings import Settings
from src.knowledge.encryptor import Encryptor
from src.server.mcp_server import (
    _EXCLUDE_TOOLS,
    _POLICY_FIELDS,
    _TOOL_SCHEMAS,
    _build_http_app,
)

from .conftest import mint_token, patch_jwks

_FERNET = Encryptor.generate_key()


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        MCP_TWIN_AUDIENCE="mcp:config-mcp",
        URL_ADMIN_TWIN_JWKS="http://admin.local/jwks.json",
        CONFIG_MCP_MASTER_KEY=_FERNET,
    )


def _client() -> TestClient:
    settings = _settings()
    enc = Encryptor(settings.resolve_master_key())
    return TestClient(_build_http_app(settings, enc))


def _decode(resp) -> dict:
    body = resp.json()
    return json.loads(body["result"]["content"][0]["text"])


def test_health() -> None:
    resp = _client().get("/v1/health")
    assert resp.status_code == 200
    assert resp.json()["service"] == "config-mcp"


def test_list_tools_carries_policy_fields() -> None:
    resp = _client().get("/mcp/tools/list")
    assert resp.status_code == 200
    tools = resp.json()["result"]["tools"]
    assert len(tools) == len(_TOOL_SCHEMAS)
    for entry in tools:
        assert entry["inputSchema"]["type"] == "object"
        for field in _POLICY_FIELDS:
            assert entry[field]


def test_status_is_exempt_no_token() -> None:
    resp = _client().post("/mcp/tools/call", json={"params": {"name": "status", "arguments": {}}})
    assert resp.status_code == 200
    payload = _decode(resp)
    assert payload["status"] == "ok"
    assert payload["service"] == "config-mcp"


def test_excluded_tool_is_denied() -> None:
    # get_credential devolve segredo em claro → nunca sai pelo gateway (fail-safe).
    assert "get_credential" in _EXCLUDE_TOOLS
    resp = _client().post(
        "/mcp/tools/call",
        json={"params": {"name": "get_credential", "arguments": {"namespace": "x", "key": "y"}}},
    )
    assert resp.status_code == 403
    assert resp.json()["error"] == "tool_excluded"


def test_missing_token_rejected() -> None:
    resp = _client().post("/mcp/tools/call", json={"params": {"name": "get_physical_info", "arguments": {}}})
    assert resp.status_code == 401
    assert resp.json()["error"] == "missing_twin_token"


def test_invalid_audience_rejected(monkeypatch, rsa_key) -> None:
    patch_jwks(monkeypatch, rsa_key)
    bad = mint_token(rsa_key, aud="mcp:outra")  # audiência divergente → rejeita
    resp = _client().post(
        "/mcp/tools/call",
        json={"params": {"name": "get_physical_info", "arguments": {}, "_meta": {"twin_token": bad}}},
    )
    assert resp.status_code == 401
    assert resp.json()["error"] == "invalid_twin_token"


def test_missing_tenant_scope_rejected(monkeypatch, rsa_key) -> None:
    patch_jwks(monkeypatch, rsa_key)
    no_tenant = mint_token(rsa_key, tenant_id=None)  # token válido, sem tenant_id
    resp = _client().post(
        "/mcp/tools/call",
        json={"params": {"name": "get_physical_info", "arguments": {}, "_meta": {"twin_token": no_tenant}}},
    )
    assert resp.status_code == 401
    assert resp.json()["error"] == "missing_tenant_scope"


def test_valid_token_storeless_dispatch(monkeypatch, rsa_key) -> None:
    # Token RS256 válido → get_physical_info (storeless) roda sem abrir sessão de tenant.
    patch_jwks(monkeypatch, rsa_key)
    good = mint_token(rsa_key)
    resp = _client().post(
        "/mcp/tools/call",
        json={"params": {"name": "get_physical_info", "arguments": {}, "_meta": {"twin_token": good}}},
    )
    assert resp.status_code == 200
    payload = _decode(resp)
    assert payload["success"] is True
    assert "cpu" in payload


def test_unknown_tool_returns_404(monkeypatch, rsa_key) -> None:
    patch_jwks(monkeypatch, rsa_key)
    good = mint_token(rsa_key)
    resp = _client().post(
        "/mcp/tools/call",
        json={"params": {"name": "does_not_exist", "arguments": {}, "_meta": {"twin_token": good}}},
    )
    assert resp.status_code == 404
    assert resp.json()["error"] == "unknown_tool"
