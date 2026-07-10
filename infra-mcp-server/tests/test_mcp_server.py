"""Testes do sidecar mcp_http + PEP inner-token (STD-MCP-001 / STD-SEC-006).

Cobre: /v1/health, /mcp/tools/list (campos de policy), /mcp/tools/call
(missing/invalid token, exempt, tenant das claims, exclude, unknown, happy path,
erro interno) e _verify_inner_token (não configurado + decode mockado). O
PyJWKClient/JWKS é sempre mockado e o AllocatorStore usa SQLite :memory: — os
testes nunca fazem I/O de rede (FID-01 / Test Doubles Policy).
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from src.config.settings import Settings
from src.db.allocator_store import AllocatorPolicy, AllocatorStore
from src.server import mcp_server as M


def _settings() -> Settings:
    return Settings(
        MCP_TWIN_AUDIENCE="mcp:infra-mcp",
        URL_ADMIN_TWIN_JWKS="http://admin.local/.well-known/jwks.json",
    )


@pytest.fixture()
def allocator() -> AllocatorStore:
    return AllocatorStore(policy=AllocatorPolicy(max_cost_usd_per_hour=20.0))


@pytest.fixture()
def client(allocator: AllocatorStore) -> TestClient:
    return TestClient(M._build_http_app(_settings(), allocator))


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
        # required_scope no formato dominio:tipo:acao (3 segmentos)
        assert t["required_scope"].count(":") == 2
        assert t["capability"] == f"infra-mcp.{t['name']}"
        assert t["required_scope"].startswith("infra-mcp:")
    by_name = {t["name"]: t for t in tools}
    # mutações usam verbo :write; consultas/plan/scan :read
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
        json={
            "params": {
                "name": "list_pool",
                "arguments": {},
                "_meta": {"twin_token": "tok"},
            }
        },
    )
    assert r.status_code == 401
    assert r.json()["error"] == "invalid_twin_token"


# ── /mcp/tools/call — token válido injeta tenant das claims (INV-3) ────────────
def test_call_valid_token_injects_tenant_from_claims(client: TestClient, monkeypatch):
    captured: dict = {}

    monkeypatch.setattr(M, "_verify_inner_token", lambda _t, _s: {"tenant_id": "T-42", "jti": "j"})

    def _spy(name, args, _settings, _allocator):
        captured["name"] = name
        captured["args"] = dict(args)
        return {"ok": True}

    monkeypatch.setattr(M, "_dispatch", _spy)
    r = client.post(
        "/mcp/tools/call",
        json={
            "params": {
                "name": "list_pool",
                # tenant do cliente deve ser IGNORADO/sobrescrito pelas claims
                "arguments": {"tenant_id": "ATTACKER"},
                "_meta": {"twin_token": "tok"},
            }
        },
    )
    assert r.status_code == 200
    assert captured["name"] == "list_pool"
    assert captured["args"]["tenant_id"] == "T-42"  # das claims, não "ATTACKER"


# ── /mcp/tools/call — token sem tenant nas claims → 401 ───────────────────────
def test_call_valid_token_without_tenant(client: TestClient, monkeypatch):
    monkeypatch.setattr(M, "_verify_inner_token", lambda _t, _s: {"jti": "j"})
    r = client.post(
        "/mcp/tools/call",
        json={
            "params": {
                "name": "list_pool",
                "arguments": {},
                "_meta": {"twin_token": "t"},
            }
        },
    )
    assert r.status_code == 401
    assert r.json()["error"] == "missing_tenant_scope"


# ── /mcp/tools/call — happy path: token válido → executa e strippa tenant ─────
def test_call_valid_token_happy_path(client: TestClient, monkeypatch):
    monkeypatch.setattr(M, "_verify_inner_token", lambda _t, _s: {"tenant_id": "T-1", "jti": "j"})
    r = client.post(
        "/mcp/tools/call",
        json={
            "params": {
                "name": "list_pool",
                "arguments": {},
                "_meta": {"twin_token": "tok"},
            }
        },
    )
    assert r.status_code == 200
    payload = json.loads(r.json()["result"]["content"][0]["text"])
    # tenant_id injetado foi removido pelo dispatcher → a tool executou com sucesso
    assert payload["vms"] == []


# ── /mcp/tools/call — tool exempt (sem token) via monkeypatch ─────────────────
def test_call_exempt_tool_without_token(client: TestClient, monkeypatch):
    monkeypatch.setattr(M, "_EXEMPT_TOOLS", frozenset({"list_pool"}))
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "list_pool", "arguments": {}}},
    )
    assert r.status_code == 200
    payload = json.loads(r.json()["result"]["content"][0]["text"])
    assert payload["vms"] == []


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

    def _boom(name, args, _settings, _allocator):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(M, "_dispatch", _boom)
    r = client.post(
        "/mcp/tools/call",
        json={
            "params": {
                "name": "list_pool",
                "arguments": {},
                "_meta": {"twin_token": "t"},
            }
        },
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


# ── _EXEMPT/_EXCLUDE são vazios por default; audiência default consistente ─────
def test_gateway_invariants_defaults():
    assert M._EXEMPT_TOOLS == frozenset()
    assert M._EXCLUDE_TOOLS == frozenset()
    assert Settings().mcp_twin_audience == "mcp:infra-mcp"


# ── build_server smoke (cobre a fábrica + stdio Server + provisioner mock) ─────
def test_build_server_smoke(monkeypatch):
    from src.config import settings as settings_mod

    settings_mod.get_settings.cache_clear()
    monkeypatch.setenv("MCP_TWIN_AUDIENCE", "mcp:infra-mcp")
    monkeypatch.setenv("URL_ADMIN_TWIN_JWKS", "http://admin.local/jwks")
    server, settings, allocator, http_app = M.build_server()
    assert server is not None
    assert isinstance(allocator, AllocatorStore)
    assert settings.mcp_twin_audience == "mcp:infra-mcp"
    assert http_app.title.startswith("infra-mcp")
    # health continua acessível no http_app retornado
    resp = TestClient(http_app).get("/v1/health")
    assert resp.json()["service"] == "infra-mcp"
    settings_mod.get_settings.cache_clear()
