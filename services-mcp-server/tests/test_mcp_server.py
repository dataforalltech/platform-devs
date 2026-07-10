"""Testes do sidecar mcp_http + PEP inner-token (STD-MCP-001 / STD-SEC-006).

Cobre: /v1/health, /mcp/tools/list (campos de policy por tool), /mcp/tools/call
(missing/invalid token, tenant das claims, tenant ausente, exempt, exclude,
unknown, internal-error, happy path) e _verify_inner_token (configurado/não).
O PyJWKClient/JWKS é sempre mockado e o PostgreSQL é substituído pelo
``InMemoryServiceStore`` — os testes nunca fazem I/O de rede/DB.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from src.config.settings import ServicesSettings
from src.server import mcp_server as M

from .conftest import InMemoryServiceStore


def _settings() -> ServicesSettings:
    return ServicesSettings(
        MCP_TWIN_AUDIENCE="mcp:services-mcp",
        URL_ADMIN_TWIN_JWKS="http://admin.local/.well-known/jwks.json",
    )


@pytest.fixture()
def store() -> InMemoryServiceStore:
    return InMemoryServiceStore()


@pytest.fixture()
def client(store: InMemoryServiceStore) -> TestClient:
    return TestClient(M._build_http_app(_settings(), store))


# ── /v1/health ────────────────────────────────────────────────────────────────
def test_health(client: TestClient):
    r = client.get("/v1/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "service": "services-mcp", "tools": 32}


# ── /mcp/tools/list — todos os 4 campos de policy (CI-2) ──────────────────────
def test_tools_list_has_policy_fields(client: TestClient):
    r = client.get("/mcp/tools/list")
    assert r.status_code == 200
    tools = r.json()["result"]["tools"]
    assert len(tools) == 32
    for t in tools:
        assert t["inputSchema"]["type"] == "object"
        for field in ("capability", "required_scope", "resource_type", "data_domain"):
            assert t[field], f"{t['name']} sem {field}"
        # required_scope no formato dominio:tipo:acao (3 segmentos)
        assert t["required_scope"].count(":") == 2
        assert t["capability"] == f"services-mcp.{t['name']}"
        assert t["required_scope"].startswith("services-mcp:")
        assert t["required_scope"].rsplit(":", 1)[1] in ("read", "write")
    by_name = {t["name"]: t for t in tools}
    # mutações usam verbo :write; consultas :read
    assert by_name["register_service"]["required_scope"].endswith(":write")
    assert by_name["reload_service"]["required_scope"].endswith(":write")
    assert by_name["launch_service"]["required_scope"].endswith(":write")
    assert by_name["set_env_var"]["required_scope"].endswith(":write")
    assert by_name["list_services"]["required_scope"].endswith(":read")
    assert by_name["get_port_map"]["required_scope"].endswith(":read")
    assert by_name["check_health"]["required_scope"].endswith(":read")
    # resource_type / data_domain amostrados
    assert by_name["get_service_logs"]["data_domain"] == "observability"
    assert by_name["set_env_var"]["data_domain"] == "configuration"
    assert by_name["register_service"]["resource_type"] == "service"


# ── /mcp/tools/call — sem inner token → 401 ───────────────────────────────────
def test_call_missing_twin_token(client: TestClient):
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "get_port_map", "arguments": {}}},
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
                "name": "get_port_map",
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

    def _spy(name, args, _store, _settings):
        captured["name"] = name
        captured["args"] = dict(args)
        return {"ok": True}

    monkeypatch.setattr(M, "_dispatch", _spy)
    r = client.post(
        "/mcp/tools/call",
        json={
            "params": {
                "name": "get_port_map",
                # tenant do cliente deve ser IGNORADO/sobrescrito pelas claims
                "arguments": {"tenant_id": "ATTACKER"},
                "_meta": {"twin_token": "tok"},
            }
        },
    )
    assert r.status_code == 200
    assert captured["name"] == "get_port_map"
    assert captured["args"]["tenant_id"] == "T-42"  # das claims, não "ATTACKER"


# ── /mcp/tools/call — token sem tenant nas claims → 401 ───────────────────────
def test_call_valid_token_without_tenant(client: TestClient, monkeypatch):
    monkeypatch.setattr(M, "_verify_inner_token", lambda _t, _s: {"jti": "j"})
    r = client.post(
        "/mcp/tools/call",
        json={
            "params": {
                "name": "get_port_map",
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
                "name": "get_port_map",
                "arguments": {},
                "_meta": {"twin_token": "tok"},
            }
        },
    )
    assert r.status_code == 200
    payload = json.loads(r.json()["result"]["content"][0]["text"])
    # tenant_id injetado foi removido pelo dispatcher → a tool executou com sucesso
    assert payload["total"] == 0
    assert "port_map" in payload


# ── /mcp/tools/call — tool exempt (sem token) via monkeypatch ─────────────────
def test_call_exempt_tool_without_token(client: TestClient, monkeypatch):
    monkeypatch.setattr(M, "_EXEMPT_TOOLS", frozenset({"list_environments"}))
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "list_environments", "arguments": {}}},
    )
    assert r.status_code == 200
    payload = json.loads(r.json()["result"]["content"][0]["text"])
    assert payload["total_services"] == 0


# ── /mcp/tools/call — denylist (exclude) → 403 ────────────────────────────────
def test_call_excluded_tool(client: TestClient, monkeypatch):
    monkeypatch.setattr(M, "_EXCLUDE_TOOLS", frozenset({"get_port_map"}))
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "get_port_map", "arguments": {}}},
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

    def _boom(name, args, _store, _settings):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(M, "_dispatch", _boom)
    r = client.post(
        "/mcp/tools/call",
        json={
            "params": {
                "name": "get_port_map",
                "arguments": {},
                "_meta": {"twin_token": "t"},
            }
        },
    )
    assert r.status_code == 200
    payload = json.loads(r.json()["result"]["content"][0]["text"])
    assert payload["error"] == "internal_error"
    assert "kaboom" in payload["detail"]


# ── _dispatch strippa tenant_id antes de chamar a tool (INV-3) ────────────────
def test_dispatch_strips_tenant_id(store: InMemoryServiceStore):
    s = _settings()
    result = M._dispatch("find_by_port", {"port": 8080, "tenant_id": "T"}, store, s)
    assert result["found"] is False
    assert result["port"] == 8080


def test_dispatch_unknown_raises_key_error(store: InMemoryServiceStore):
    with pytest.raises(KeyError):
        M._dispatch("does_not_exist", {}, store, _settings())


# ── _verify_inner_token não configurado → PermissionError (fail-closed) ────────
def test_verify_inner_token_unconfigured():
    s = ServicesSettings(MCP_TWIN_AUDIENCE="", URL_ADMIN_TWIN_JWKS="")
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
    assert captured["audience"] == "mcp:services-mcp"
    assert set(captured["options"]["require"]) == {"exp", "aud", "jti"}


# ── build_server smoke (cobre a fábrica + stdio Server; store faked) ──────────
def test_build_server_smoke(monkeypatch):
    monkeypatch.setattr(M, "ServiceStore", InMemoryServiceStore)
    from src.config import settings as settings_mod

    settings_mod.get_settings.cache_clear()
    server, settings, store, http_app = M.build_server()
    assert server is not None
    assert isinstance(store, InMemoryServiceStore)
    assert settings.mcp_twin_audience == "mcp:services-mcp"
    assert http_app.title.startswith("services-mcp")
    resp = TestClient(http_app).get("/v1/health")
    assert resp.json()["service"] == "services-mcp"
    settings_mod.get_settings.cache_clear()
