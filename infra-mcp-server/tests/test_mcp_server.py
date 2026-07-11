"""Testes do sidecar mcp_http + PEP inner-token (STD-MCP-001 / STD-SEC-006).

Cobre: /v1/health, /mcp/tools/list (campos de policy), /mcp/tools/call (missing/invalid
token, tenant das claims, exempt, exclude, unknown, erro interno), _verify_inner_token e
build_server. As unidades mockam ``_run_tool`` (sem I/O de DB); o teste end-to-end
(``@integration``) exercita o caminho real for_tenant→schema→store contra MySQL + RS256 real.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from src.config.settings import Settings
from src.db.provisioner import ImmediateProvisioner
from src.server import mcp_server as M

from .conftest import TENANT_A, mint_token, patch_jwks, requires_mysql


def _settings() -> Settings:
    return Settings(
        MCP_TWIN_AUDIENCE="mcp:infra-mcp",
        URL_ADMIN_TWIN_JWKS="http://admin.local/.well-known/jwks.json",
    )


@pytest.fixture()
def client() -> TestClient:
    return TestClient(M._build_http_app(_settings(), ImmediateProvisioner(), None))


# ── /v1/health ────────────────────────────────────────────────────────────────
def test_health(client: TestClient):
    r = client.get("/v1/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "service": "infra-mcp", "tools": len(M._TOOL_SCHEMAS)}


# ── /mcp/tools/list — todos os 4 campos de policy (CI-2) ──────────────────────
def test_tools_list_has_policy_fields(client: TestClient):
    r = client.get("/mcp/tools/list")
    assert r.status_code == 200
    tools = r.json()["result"]["tools"]
    assert {t["name"] for t in tools} == set(M._TOOL_SCHEMAS.keys())
    assert len(tools) == 15
    for t in tools:
        assert t["inputSchema"]["type"] == "object"
        for field in ("capability", "required_scope", "resource_type", "data_domain"):
            assert t[field], f"{t['name']} sem {field}"
        assert t["required_scope"].count(":") == 2  # dominio:tipo:acao
        assert t["capability"] == f"infra-mcp.{t['name']}"
        assert t["required_scope"].startswith("infra-mcp:")
    by_name = {t["name"]: t for t in tools}
    assert by_name["request_vm"]["required_scope"].endswith(":write")
    assert by_name["release_lease"]["required_scope"].endswith(":write")
    assert by_name["get_lease_ssh_key"]["required_scope"] == "infra-mcp:secret:write"
    assert by_name["terraform_validate"]["required_scope"].endswith(":read")
    assert by_name["query_capacity"]["required_scope"].endswith(":read")
    assert by_name["cost_estimate_infracost"]["data_domain"] == "finops"


# ── /mcp/tools/call — sem inner token → 401 ───────────────────────────────────
def test_call_missing_twin_token(client: TestClient):
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "query_capacity", "arguments": {"spec": "cpu-small"}}},
    )
    assert r.status_code == 401
    assert r.json()["error"] == "missing_twin_token"


# ── /mcp/tools/call — inner token inválido → 401 (fail-closed) ─────────────────
def test_call_invalid_twin_token(client: TestClient, monkeypatch):
    def _boom(_tok, _settings):
        raise ValueError("bad signature")

    monkeypatch.setattr(M, "_verify_inner_token", _boom)
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "list_pool", "arguments": {}, "_meta": {"twin_token": "tok"}}},
    )
    assert r.status_code == 401
    assert r.json()["error"] == "invalid_twin_token"


# ── /mcp/tools/call — token válido: tenant vem das claims (INV-3) ──────────────
def test_call_valid_token_uses_tenant_from_claims(client: TestClient, monkeypatch):
    captured: dict = {}

    monkeypatch.setattr(M, "_verify_inner_token", lambda _t, _s: {"tenant_id": "T-42", "jti": "j"})

    async def _spy(name, arguments, _settings, tenant_id, _prov, _fk):
        captured["name"] = name
        captured["tenant_id"] = tenant_id
        captured["args"] = dict(arguments)
        return {"ok": True}

    monkeypatch.setattr(M, "_run_tool", _spy)
    r = client.post(
        "/mcp/tools/call",
        json={
            "params": {
                "name": "list_pool",
                # tenant do cliente deve ser IGNORADO (nunca chega ao _run_tool)
                "arguments": {"tenant_id": "ATTACKER"},
                "_meta": {"twin_token": "tok"},
            }
        },
    )
    assert r.status_code == 200
    assert captured["name"] == "list_pool"
    assert captured["tenant_id"] == "T-42"  # das claims, não "ATTACKER"


# ── /mcp/tools/call — token sem tenant nas claims → 401 ───────────────────────
def test_call_valid_token_without_tenant(client: TestClient, monkeypatch):
    monkeypatch.setattr(M, "_verify_inner_token", lambda _t, _s: {"jti": "j"})
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "list_pool", "arguments": {}, "_meta": {"twin_token": "t"}}},
    )
    assert r.status_code == 401
    assert r.json()["error"] == "missing_tenant_scope"


# ── /mcp/tools/call — tool exempt (sem token) via monkeypatch ─────────────────
def test_call_exempt_tool_without_token(client: TestClient, monkeypatch):
    monkeypatch.setattr(M, "_EXEMPT_TOOLS", frozenset({"list_pool"}))

    async def _spy(name, arguments, _settings, tenant_id, _prov, _fk):
        return {"exempt_ran": True, "tenant": tenant_id}

    monkeypatch.setattr(M, "_run_tool", _spy)
    r = client.post("/mcp/tools/call", json={"params": {"name": "list_pool", "arguments": {}}})
    assert r.status_code == 200
    payload = json.loads(r.json()["result"]["content"][0]["text"])
    assert payload["exempt_ran"] is True


# ── /mcp/tools/call — denylist (exclude) → 403 ────────────────────────────────
def test_call_excluded_tool(client: TestClient, monkeypatch):
    monkeypatch.setattr(M, "_EXCLUDE_TOOLS", frozenset({"get_lease_ssh_key"}))
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "get_lease_ssh_key", "arguments": {"lease_id": "x", "owner": "o"}}},
    )
    assert r.status_code == 403
    assert r.json()["error"] == "tool_excluded"


# ── /mcp/tools/call — tool desconhecida → 404 ─────────────────────────────────
def test_call_unknown_tool(client: TestClient, monkeypatch):
    monkeypatch.setattr(M, "_verify_inner_token", lambda _t, _s: {"tenant_id": "T"})
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "nope", "arguments": {}, "_meta": {"twin_token": "t"}}},
    )
    assert r.status_code == 404
    assert r.json()["error"] == "unknown_tool"


# ── /mcp/tools/call — erro interno na tool → payload internal_error ────────────
def test_call_internal_error(client: TestClient, monkeypatch):
    monkeypatch.setattr(M, "_verify_inner_token", lambda _t, _s: {"tenant_id": "T"})

    async def _boom(*_a, **_kw):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(M, "_run_tool", _boom)
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "list_pool", "arguments": {}, "_meta": {"twin_token": "t"}}},
    )
    assert r.status_code == 200
    payload = json.loads(r.json()["result"]["content"][0]["text"])
    assert payload["error"] == "internal_error"
    assert "kaboom" in payload["detail"]


# ── _verify_inner_token não configurado → PermissionError (fail-closed) ────────
def test_verify_inner_token_unconfigured():
    s = Settings(MCP_TWIN_AUDIENCE="", URL_ADMIN_TWIN_JWKS="")
    with pytest.raises(PermissionError):
        M._verify_inner_token("tok", s)


# ── _verify_inner_token configurado usa PyJWKClient + jwt.decode (mockado) ─────
def test_verify_inner_token_decodes(monkeypatch):
    s = _settings()

    class _FakeKey:
        key = "K"

    class _FakeJWK:
        def __init__(self, _url):
            pass

        def get_signing_key_from_jwt(self, _tok):
            return _FakeKey()

    captured: dict = {}

    def _decode(tok, key, algorithms, audience, options):
        captured.update(algorithms=algorithms, audience=audience, options=options)
        return {"tenant_id": "T", "jti": "j"}

    monkeypatch.setattr(M.jwt, "PyJWKClient", _FakeJWK)
    monkeypatch.setattr(M.jwt, "decode", _decode)
    claims = M._verify_inner_token("tok", s)
    assert claims["tenant_id"] == "T"
    assert captured["algorithms"] == ["RS256"]
    assert captured["audience"] == "mcp:infra-mcp"
    assert set(captured["options"]["require"]) == {"exp", "aud", "jti"}


# ── invariantes de gateway (defaults) ─────────────────────────────────────────
def test_gateway_invariants_defaults():
    assert M._EXEMPT_TOOLS == frozenset()
    assert M._EXCLUDE_TOOLS == frozenset()
    assert Settings().mcp_twin_audience == "mcp:infra-mcp"
    assert M._ALLOCATOR_TOOLS <= set(M._TOOL_SCHEMAS)
    assert len(M._ALLOCATOR_TOOLS) == 9


# ── build_server smoke (fábrica + configure + provisioner mock) ───────────────
def test_build_server_smoke(monkeypatch):
    from src.config import settings as settings_mod

    settings_mod.get_settings.cache_clear()
    monkeypatch.setenv("MCP_TWIN_AUDIENCE", "mcp:infra-mcp")
    monkeypatch.setenv("URL_ADMIN_TWIN_JWKS", "http://admin.local/jwks")
    server, settings, http_app = M.build_server()
    assert server is not None
    assert settings.mcp_twin_audience == "mcp:infra-mcp"
    assert http_app.title.startswith("infra-mcp")
    resp = TestClient(http_app).get("/v1/health")
    assert resp.json()["service"] == "infra-mcp"
    settings_mod.get_settings.cache_clear()


# ── stdio é gateway-only: recusa fail-closed (sem tenant) ─────────────────────
def test_stdio_refuses_fail_closed():
    known = M._stdio_refuse("list_pool")
    assert known["error"] == "tenant_context_required"
    unknown = M._stdio_refuse("nope")
    assert unknown["error"] == "unknown_tool"


# ── End-to-end real: for_tenant → schema → store (MySQL + RS256 reais) ────────
@pytest.mark.integration
@requires_mysql
def test_end_to_end_request_vm(monkeypatch, rsa_key, seed_platforms):
    patch_jwks(monkeypatch, rsa_key)
    app = M._build_http_app(_settings(), ImmediateProvisioner(), None)
    monkeypatch.setattr(M, "_SCHEMA_READY", set())
    token = mint_token(rsa_key, tenant_id=TENANT_A, aud="mcp:infra-mcp")
    with TestClient(app) as client:
        r = client.post(
            "/mcp/tools/call",
            json={
                "params": {
                    "name": "request_vm",
                    "arguments": {"spec": "cpu-small", "duration_min": 60, "owner": "e2e"},
                    "_meta": {"twin_token": token},
                }
            },
        )
    assert r.status_code == 200
    payload = json.loads(r.json()["result"]["content"][0]["text"])
    assert payload["outcome"] == "LEASED"
    assert payload["lease"]["status"] == "ACTIVE"
