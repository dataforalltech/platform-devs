"""Sidecar mcp_http + PEP inner-token (RS256 REAL) — §16 / Test Doubles Policy.

RS256 é real: chave gerada, token assinado, verificador real (o PyJWKClient serve a
chave pública local — sem bypass, sem HS*). O caminho de execução com estado (happy
path / dispatch / unknown) roda contra MySQL real via `_run_tool`/`_dispatch`.
"""

from __future__ import annotations

import json

import jwt
import pytest
from fastapi.testclient import TestClient
from platform_database import close_tenant_pools

from src.config.settings import DevTwinSettings
from src.server import mcp_server as M

from .conftest import TENANT_A, _test_settings, mint_token, patch_jwks, requires_mysql

_ALL_TOOLS = {
    "status",
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


@pytest.fixture
def client() -> TestClient:
    return TestClient(M._build_http_app(_test_settings()))


# ── Schemas / catálogo (sem DB) ───────────────────────────────────────────────
def test_tool_count():
    assert len(M._TOOL_SCHEMAS) == 10


def test_required_fields_are_subset_of_properties():
    for name, meta in M._TOOL_SCHEMAS.items():
        props = set(meta["schema"].get("properties", {}).keys())
        required = set(meta["schema"].get("required", []))
        assert required <= props, f"{name}: required fora de properties"


def test_health(client: TestClient):
    r = client.get("/v1/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "service": "dev-twin-mcp", "tools": 10}


def test_tools_list_has_policy_fields(client: TestClient):
    tools = client.get("/mcp/tools/list").json()["result"]["tools"]
    assert {t["name"] for t in tools} == _ALL_TOOLS
    for t in tools:
        assert t["inputSchema"]["type"] == "object"
        for field in ("capability", "required_scope", "resource_type", "data_domain"):
            assert t[field], f"{t['name']} sem {field}"
        assert t["required_scope"].count(":") == 2
        assert t["capability"] == f"dev-twin-mcp.{t['name']}"
    by_name = {t["name"]: t for t in tools}
    # leituras usam :read; mutações usam :write
    assert by_name["status"]["required_scope"].endswith(":read")
    assert by_name["whoami"]["required_scope"].endswith(":read")
    assert by_name["list_tokens"]["required_scope"].endswith(":read")
    assert by_name["authenticate"]["required_scope"].endswith(":write")
    assert by_name["register_token"]["required_scope"].endswith(":write")


# ── /mcp/tools/call — tool exempt (sem token, sem DB) ─────────────────────────
def test_call_exempt_status_without_token(client: TestClient):
    r = client.post("/mcp/tools/call", json={"params": {"name": "status", "arguments": {}}})
    assert r.status_code == 200
    text = r.json()["result"]["content"][0]["text"]
    assert json.loads(text)["status"] == "ok"


# ── /mcp/tools/call — PEP (RS256 real), caminhos que retornam antes do DB ──────
def test_call_missing_twin_token(client: TestClient):
    r = client.post("/mcp/tools/call", json={"params": {"name": "whoami", "arguments": {}}})
    assert r.status_code == 401 and r.json()["error"] == "missing_twin_token"


def test_call_invalid_audience_rejected(client: TestClient, monkeypatch, rsa_key):
    patch_jwks(monkeypatch, rsa_key)
    tok = mint_token(rsa_key, aud="mcp:outro-servico")  # audiência errada → verificador real rejeita
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "whoami", "arguments": {}, "_meta": {"twin_token": tok}}},
    )
    assert r.status_code == 401 and r.json()["error"] == "invalid_twin_token"


def test_call_token_without_jti_rejected(client: TestClient, monkeypatch, rsa_key):
    patch_jwks(monkeypatch, rsa_key)
    tok = mint_token(rsa_key, include_jti=False)  # sem jti → require falha
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "whoami", "arguments": {}, "_meta": {"twin_token": tok}}},
    )
    assert r.status_code == 401 and r.json()["error"] == "invalid_twin_token"


def test_call_token_without_tenant(client: TestClient, monkeypatch, rsa_key):
    patch_jwks(monkeypatch, rsa_key)
    tok = mint_token(rsa_key, tenant_id=None)  # verifica OK mas sem tenant nas claims
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "whoami", "arguments": {}, "_meta": {"twin_token": tok}}},
    )
    assert r.status_code == 401 and r.json()["error"] == "missing_tenant_scope"


# ── /mcp/tools/call — denylist (register/rotate retornam segredo) → 403 ───────
def test_call_excluded_register_token(client: TestClient):
    # excluída ANTES da verificação de token (fail-safe): 403 mesmo sem twin_token.
    r = client.post("/mcp/tools/call", json={"params": {"name": "register_token", "arguments": {}}})
    assert r.status_code == 403 and r.json()["error"] == "tool_excluded"


def test_call_excluded_rotate_token(client: TestClient):
    r = client.post("/mcp/tools/call", json={"params": {"name": "rotate_token", "arguments": {}}})
    assert r.status_code == 403 and r.json()["error"] == "tool_excluded"


# ── /mcp/tools/call — tool desconhecida (não-store) → 404 ─────────────────────
def test_call_unknown_tool(client: TestClient, monkeypatch, rsa_key):
    patch_jwks(monkeypatch, rsa_key)
    tok = mint_token(rsa_key, tenant_id="T")
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "nope", "arguments": {}, "_meta": {"twin_token": tok}}},
    )
    assert r.status_code == 404 and r.json()["error"] == "unknown_tool"


# ── _verify_inner_token (RS256 real) ──────────────────────────────────────────
def test_verify_inner_token_unconfigured():
    s = DevTwinSettings(MCP_TWIN_AUDIENCE="", URL_ADMIN_TWIN_JWKS="")
    with pytest.raises(PermissionError):
        M._verify_inner_token("tok", s)


def test_verify_inner_token_real_rs256(monkeypatch, rsa_key):
    patch_jwks(monkeypatch, rsa_key)
    claims = M._verify_inner_token(mint_token(rsa_key, tenant_id="T-9"), _test_settings())
    assert claims["tenant_id"] == "T-9"
    with pytest.raises(jwt.InvalidAudienceError):
        M._verify_inner_token(mint_token(rsa_key, aud="mcp:x"), _test_settings())


# ── stdio call_tool → recusa fail-closed (gateway-only) + smoke ───────────────
def test_build_server_stdio_and_smoke(monkeypatch):
    monkeypatch.setattr(M, "get_settings", lambda: _test_settings())
    server, settings, http_app = M.build_server()
    assert settings.mcp_twin_audience == "mcp:dev-twin-mcp"
    assert http_app.title.startswith("dev-twin-mcp")
    assert TestClient(http_app).get("/v1/health").json()["service"] == "dev-twin-mcp"


# ── main(): branch HTTP-only e branch stdio ───────────────────────────────────
def test_main_http_only(monkeypatch):
    monkeypatch.setenv("MCP_HTTP_ONLY", "1")
    monkeypatch.setattr(M, "get_settings", lambda: _test_settings())
    calls = {}
    import uvicorn

    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: calls.update(app=app, kw=kw))
    M.main()
    assert calls["kw"]["port"] == 7100


def test_main_stdio(monkeypatch):
    monkeypatch.setenv("MCP_HTTP_ONLY", "0")
    captured = {}

    def _fake_asyncio_run(coro):
        captured["ran"] = True
        coro.close()  # evita 'coroutine was never awaited'

    monkeypatch.setattr(M.asyncio, "run", _fake_asyncio_run)
    M.main()
    assert captured["ran"] is True


# ── Execução com estado (MySQL real): _dispatch roteando todas as tools ───────
@pytest.mark.integration
@requires_mysql
async def test_dispatch_routes_all_tools(store_a):
    s = _test_settings()

    async def d(name, args, store):
        return await M._dispatch(name, args, s, store)

    # sessão/status (sem store)
    assert (await d("status", {}, None))["status"] == "ok"
    assert (await d("whoami", {}, None))["authenticated"] is False
    assert (await d("get_twin_context", {}, None))["authenticated"] is False
    assert (await d("context_status", {}, None))["authenticated"] is False
    assert (await d("refresh_context", {}, None))["success"] is False

    # store tools (agent_tokens no MySQL real)
    reg = await d(
        "register_token",
        {"admin_token": "admin-secret-token-for-tests", "name": "Carol", "email": "c@test.com"},
        store_a,
    )
    assert reg["success"] is True
    assert (await d("authenticate", {"token": reg["token"]}, store_a))["authenticated"] is True
    assert (await d("whoami", {}, None))["name"] == "Carol"
    listed = await d("list_tokens", {"admin_token": "admin-secret-token-for-tests"}, store_a)
    assert listed["count"] >= 1
    rot = await d(
        "rotate_token",
        {"admin_token": "admin-secret-token-for-tests", "identifier": reg["user_id"]},
        store_a,
    )
    assert rot["success"] is True
    rev = await d(
        "revoke_token",
        {"admin_token": "admin-secret-token-for-tests", "identifier": rot["user_id"]},
        store_a,
    )
    assert rev["success"] is True

    # store tool sem store (defensivo) e tool desconhecida → KeyError
    with pytest.raises(KeyError):
        await d("authenticate", {"token": "x"}, None)
    with pytest.raises(KeyError):
        await d("does_not_exist", {}, store_a)


# ── Caminho credencial-zero REAL: _run_tool -> for_tenant (PLATFORMS) ─────────
@pytest.mark.integration
@requires_mysql
async def test_run_tool_credential_zero_end_to_end(seed_platforms):
    """_run_tool -> _ensure_tenant_schema -> for_tenant (get_platform -> PLATFORMS) ->
    TokenStore -> _dispatch, tudo em MySQL real."""
    M._SCHEMA_READY.discard(TENANT_A)
    settings = _test_settings()
    reg = await M._run_tool(
        "register_token",
        {"admin_token": "admin-secret-token-for-tests", "name": "E2E", "email": "e2e@test.com"},
        settings,
        TENANT_A,
    )
    assert reg["success"] is True
    auth = await M._run_tool("authenticate", {"token": reg["token"]}, settings, TENANT_A)
    assert auth["authenticated"] is True
    # status (não-store) via _run_tool não exige tenant
    assert (await M._run_tool("status", {}, settings, None))["status"] == "ok"


# ── HTTP e2e: tenant vem SEMPRE dos claims, nunca do argumento do cliente ──────
@pytest.mark.integration
@requires_mysql
async def test_call_authenticate_tenant_from_claims(seed_platforms, monkeypatch, rsa_key):
    M._SCHEMA_READY.discard(TENANT_A)
    patch_jwks(monkeypatch, rsa_key)
    client = TestClient(M._build_http_app(_test_settings()))

    # provisiona um token no banco do TENANT_A (via _run_tool, tenant real)
    reg = await M._run_tool(
        "register_token",
        {"admin_token": "admin-secret-token-for-tests", "name": "Dave", "email": "dave@test.com"},
        _test_settings(),
        TENANT_A,
    )
    # O register acima criou o pool do tenant no loop DESTE teste; o TestClient roda num
    # loop separado (portal anyio). Fecha os pools p/ o TestClient recriar no seu loop
    # (senão: "Future attached to a different loop"). O token registrado persiste no DB.
    await close_tenant_pools()
    tok = mint_token(rsa_key, tenant_id=TENANT_A)
    r = client.post(
        "/mcp/tools/call",
        json={
            "params": {
                "name": "authenticate",
                # tenant do cliente é IGNORADO — o do inner token (TENANT_A) prevalece
                "arguments": {"token": reg["token"], "tenant_id": "ATTACKER"},
                "_meta": {"twin_token": tok},
            }
        },
    )
    assert r.status_code == 200
    payload = json.loads(r.json()["result"]["content"][0]["text"])
    assert payload["authenticated"] is True
    assert payload["name"] == "Dave"
