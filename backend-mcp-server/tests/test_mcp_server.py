"""Testes do sidecar mcp_http + PEP inner-token (STD-MCP-001 / STD-SEC-006).

Cobre: /v1/health, /mcp/tools/list (campos de policy), /mcp/tools/call
(missing/invalid token, exempt, tenant das claims, exclude, unknown) e
_verify_inner_token não configurado. O PyJWKClient/JWKS é sempre mockado —
os testes nunca fazem I/O de rede (FID-01 / Test Doubles Policy).
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from src.config.settings import Settings
from src.server import mcp_server as M


def _settings() -> Settings:
    return Settings(
        MCP_TWIN_AUDIENCE="mcp:backend-mcp",
        URL_ADMIN_TWIN_JWKS="http://admin.local/.well-known/jwks.json",
    )


@pytest.fixture()
def client() -> TestClient:
    return TestClient(M._build_http_app(_settings()))


# ── /v1/health ────────────────────────────────────────────────────────────────
def test_health(client: TestClient):
    r = client.get("/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body == {"status": "ok", "service": "backend-mcp", "tools": 13}


# ── /mcp/tools/list — todos os 4 campos de policy (CI-2) ──────────────────────
def test_tools_list_has_policy_fields(client: TestClient):
    r = client.get("/mcp/tools/list")
    assert r.status_code == 200
    tools = r.json()["result"]["tools"]
    assert {t["name"] for t in tools} == {
        "analyze_backend_requirement",
        "review_backend_code",
        "optimize_query",
        "generate_api_contract",
        "generate_auth_policy",
        "generate_database_schema",
        "generate_fastapi_router",
        "generate_nestjs_controller",
        "generate_migration",
        "generate_repository_layer",
        "generate_service_layer",
        "generate_openapi_spec",
        "map_integration_flow",
    }
    for t in tools:
        assert t["inputSchema"]["type"] == "object"
        assert t["inputSchema"]["additionalProperties"] is False
        for field in ("capability", "required_scope", "resource_type", "data_domain"):
            assert t[field], f"{t['name']} sem {field}"
        # capability é o id estável <namespace>.<tool>
        assert t["capability"] == f"backend-mcp.{t['name']}"
        # required_scope no formato dominio:tipo:acao
        assert t["required_scope"].count(":") == 2
        assert t["required_scope"].startswith("backend-mcp:")
    by_name = {t["name"]: t for t in tools}
    # análise/revisão/otimização são :read; geradores/mapeamento são :write.
    assert by_name["analyze_backend_requirement"]["required_scope"].endswith(":read")
    assert by_name["review_backend_code"]["required_scope"].endswith(":read")
    assert by_name["optimize_query"]["required_scope"].endswith(":read")
    assert by_name["generate_api_contract"]["required_scope"].endswith(":write")
    assert by_name["generate_database_schema"]["required_scope"].endswith(":write")
    assert by_name["map_integration_flow"]["required_scope"].endswith(":write")
    # data_domain sensível: a auth_policy é security, o resto é backend.
    assert by_name["generate_auth_policy"]["data_domain"] == "security"


# ── /mcp/tools/call — tool exempt (sem token) ─────────────────────────────────
def test_call_exempt_tool_without_token(client: TestClient, monkeypatch):
    # backend-mcp não tem tool tokenless por padrão; exercita o caminho _EXEMPT.
    monkeypatch.setattr(M, "_EXEMPT_TOOLS", frozenset({"analyze_backend_requirement"}))
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "analyze_backend_requirement", "arguments": {"requirement": "X"}}},
    )
    assert r.status_code == 200
    text = r.json()["result"]["content"][0]["text"]
    payload = json.loads(text)
    assert payload["analysis"] == "Analyzed backend requirement: X"
    # tool exempt não recebe injeção de tenant (não passou pelo PEP).
    assert "tenant_id" not in payload


# ── /mcp/tools/call — sem inner token → 401 ───────────────────────────────────
def test_call_missing_twin_token(client: TestClient):
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "generate_api_contract", "arguments": {"endpoint": "/x"}}},
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
                "name": "generate_api_contract",
                "arguments": {"endpoint": "/x"},
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

    def _spy(name, args):
        captured["name"] = name
        captured["args"] = dict(args)
        return {"ok": True}

    monkeypatch.setattr(M, "_dispatch", _spy)
    r = client.post(
        "/mcp/tools/call",
        json={
            "params": {
                "name": "generate_api_contract",
                # tenant do cliente deve ser IGNORADO/sobrescrito pelas claims
                "arguments": {"endpoint": "/x", "tenant_id": "ATTACKER"},
                "_meta": {"twin_token": "tok"},
            }
        },
    )
    assert r.status_code == 200
    assert captured["name"] == "generate_api_contract"
    assert captured["args"]["tenant_id"] == "T-42"  # das claims, não "ATTACKER"


# ── /mcp/tools/call — token sem tenant nas claims → 401 ───────────────────────
def test_call_valid_token_without_tenant(client: TestClient, monkeypatch):
    monkeypatch.setattr(M, "_verify_inner_token", lambda _t, _s: {"jti": "j"})
    r = client.post(
        "/mcp/tools/call",
        json={
            "params": {
                "name": "generate_api_contract",
                "arguments": {},
                "_meta": {"twin_token": "t"},
            }
        },
    )
    assert r.status_code == 401
    assert r.json()["error"] == "missing_tenant_scope"


# ── /mcp/tools/call — denylist (exclude) → 403 ────────────────────────────────
def test_call_excluded_tool(client: TestClient, monkeypatch):
    monkeypatch.setattr(M, "_EXCLUDE_TOOLS", frozenset({"optimize_query"}))
    r = client.post("/mcp/tools/call", json={"params": {"name": "optimize_query", "arguments": {}}})
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


# ── /mcp/tools/call — happy path real (token válido → dispatch real) ───────────
def test_call_valid_token_dispatches_real_tool(client: TestClient, monkeypatch):
    monkeypatch.setattr(M, "_verify_inner_token", lambda _t, _s: {"tenant_id": "T-9", "jti": "j"})
    r = client.post(
        "/mcp/tools/call",
        json={
            "params": {
                "name": "generate_auth_policy",
                "arguments": {"resource": "orders", "auth_type": "jwt", "roles": ["admin"]},
                "_meta": {"twin_token": "tok"},
            }
        },
    )
    assert r.status_code == 200
    payload = json.loads(r.json()["result"]["content"][0]["text"])
    assert payload["resource"] == "orders"
    assert payload["auth_type"] == "jwt"
    assert payload["roles"] == ["admin"]


# ── /mcp/tools/call — erro interno da tool vira payload internal_error ─────────
def test_call_tool_internal_error_is_wrapped(client: TestClient, monkeypatch):
    monkeypatch.setattr(M, "_verify_inner_token", lambda _t, _s: {"tenant_id": "T"})

    def _boom(_name, _args):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(M, "_dispatch", _boom)
    r = client.post(
        "/mcp/tools/call",
        json={
            "params": {
                "name": "generate_api_contract",
                "arguments": {},
                "_meta": {"twin_token": "t"},
            }
        },
    )
    assert r.status_code == 200
    payload = json.loads(r.json()["result"]["content"][0]["text"])
    assert payload["error"] == "internal_error"
    assert payload["detail"] == "kaboom"


# ── /mcp/tools/call — body sem envelope 'params' (params = body) ───────────────
def test_call_without_params_envelope(client: TestClient):
    # params.get(...) usa o próprio body quando não há 'params' → tool não-exempt sem token.
    r = client.post("/mcp/tools/call", json={"name": "generate_api_contract", "arguments": {}})
    assert r.status_code == 401
    assert r.json()["error"] == "missing_twin_token"


# ── _dispatch cobre as 13 tools + KeyError ────────────────────────────────────
def test_dispatch_routes_all_tools():
    assert "analysis" in M._dispatch("analyze_backend_requirement", {"requirement": "R"})
    assert "security_score" in M._dispatch("review_backend_code", {"code": "x", "language": "py"})
    assert "optimizations" in M._dispatch("optimize_query", {"query": "SELECT 1", "database": "pg"})
    assert "status_codes" in M._dispatch("generate_api_contract", {"endpoint": "/x", "method": "GET"})
    assert "encryption" in M._dispatch(
        "generate_auth_policy", {"resource": "r", "auth_type": "jwt", "roles": []}
    )
    assert "indexes" in M._dispatch(
        "generate_database_schema", {"entity": "user", "attributes": [], "database": "pg"}
    )
    assert "router_name" in M._dispatch("generate_fastapi_router", {"name": "u", "base_path": "/u"})
    assert "controller_name" in M._dispatch(
        "generate_nestjs_controller", {"name": "U", "base_path": "/u"}
    )
    assert "migration_name" in M._dispatch(
        "generate_migration", {"title": "init", "operations": [], "database": "pg"}
    )
    assert "methods" in M._dispatch("generate_repository_layer", {"entity": "u", "database": "pg"})
    assert "service_name" in M._dispatch("generate_service_layer", {"name": "u", "methods": []})
    assert "openapi" in M._dispatch(
        "generate_openapi_spec", {"api_name": "API", "version": "1", "endpoints": []}
    )
    assert "retry_policy" in M._dispatch(
        "map_integration_flow", {"integration_name": "i", "external_service": "s"}
    )
    with pytest.raises(KeyError):
        M._dispatch("unknown", {})


# ── _verify_inner_token não configurado → PermissionError (fail-closed) ────────
def test_verify_inner_token_unconfigured():
    s = Settings(MCP_TWIN_AUDIENCE="", URL_ADMIN_TWIN_JWKS="")
    with pytest.raises(PermissionError):
        M._verify_inner_token("tok", s)


# ── _verify_inner_token configurado usa JWKS + jwt.decode (mockados) ───────────
def test_verify_inner_token_uses_jwks_and_decode(monkeypatch):
    class _FakeKey:
        key = "SIGNING-KEY"

    class _FakeJWKClient:
        def __init__(self, url):
            self.url = url

        def get_signing_key_from_jwt(self, _tok):
            return _FakeKey()

    captured: dict = {}

    def _fake_decode(token, key, algorithms, audience, options):
        captured.update(
            token=token, key=key, algorithms=algorithms, audience=audience, options=options
        )
        return {"tenant_id": "T-1", "jti": "j"}

    monkeypatch.setattr(M.jwt, "PyJWKClient", _FakeJWKClient)
    monkeypatch.setattr(M.jwt, "decode", _fake_decode)

    claims = M._verify_inner_token("tok", _settings())
    assert claims["tenant_id"] == "T-1"
    assert captured["algorithms"] == ["RS256"]
    assert captured["audience"] == "mcp:backend-mcp"
    assert set(captured["options"]["require"]) == {"exp", "aud", "jti"}


# ── build_server smoke (cobre a fábrica + stdio Server) ───────────────────────
def test_build_server_smoke(monkeypatch):
    monkeypatch.delenv("MCP_TWIN_AUDIENCE", raising=False)
    from src.config import settings as settings_mod

    settings_mod.get_settings.cache_clear()
    server, settings, http_app = M.build_server()
    assert server is not None
    assert settings.mcp_twin_audience == "mcp:backend-mcp"
    assert http_app.title.startswith("backend-mcp")
