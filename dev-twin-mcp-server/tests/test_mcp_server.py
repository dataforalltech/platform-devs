"""Testes do sidecar mcp_http + PEP inner-token (STD-MCP-001 / STD-SEC-006).

Cobre: /v1/health, /mcp/tools/list (campos de policy), /mcp/tools/call
(missing/invalid token, exempt, tenant das claims, exclude, unknown),
_verify_inner_token não configurado, o dispatcher completo e o build_server.

Herméticos: o pool psycopg2 é trocado por um fake in-memory e o PyJWKClient/JWKS é
sempre mockado — os testes nunca fazem I/O de rede nem tocam banco (FID-01).
"""

from __future__ import annotations

import json

import psycopg2.pool
import pytest
from fastapi.testclient import TestClient

from src.config.settings import DevTwinSettings
from src.knowledge.session import SessionManager
from src.server import mcp_server as M
from tests.conftest import _FakePool

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


def _settings() -> DevTwinSettings:
    return DevTwinSettings(
        MCP_TWIN_AUDIENCE="mcp:dev-twin-mcp",
        URL_ADMIN_TWIN_JWKS="http://admin.local/.well-known/jwks.json",
        pg_host="fake",
        pg_db="fake",
        pg_user="fake",
        pg_password="fake",
        admin_token="admin-secret",
    )


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    """Pool in-memory + store lazy resetado + sessão limpa."""
    monkeypatch.setattr(psycopg2.pool, "ThreadedConnectionPool", _FakePool)
    monkeypatch.setattr(M, "_store", None)
    SessionManager.clear()
    yield
    SessionManager.clear()


@pytest.fixture()
def settings() -> DevTwinSettings:
    return _settings()


@pytest.fixture()
def client(settings: DevTwinSettings) -> TestClient:
    return TestClient(M._build_http_app(settings))


# ── /v1/health ────────────────────────────────────────────────────────────────
def test_health(client: TestClient):
    r = client.get("/v1/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "service": "dev-twin-mcp", "tools": 10}


# ── /mcp/tools/list — todos os 4 campos de policy (CI-2) ──────────────────────
def test_tools_list_has_policy_fields(client: TestClient):
    r = client.get("/mcp/tools/list")
    assert r.status_code == 200
    tools = r.json()["result"]["tools"]
    assert {t["name"] for t in tools} == _ALL_TOOLS
    for t in tools:
        assert t["inputSchema"]["type"] == "object"
        for field in ("capability", "required_scope", "resource_type", "data_domain"):
            assert t[field], f"{t['name']} sem {field}"
        # required_scope no formato dominio:tipo:acao (2 dois-pontos)
        assert t["required_scope"].count(":") == 2
        assert t["capability"] == f"dev-twin-mcp.{t['name']}"
    by_name = {t["name"]: t for t in tools}
    # leituras usam :read; mutações usam :write
    assert by_name["status"]["required_scope"].endswith(":read")
    assert by_name["whoami"]["required_scope"].endswith(":read")
    assert by_name["list_tokens"]["required_scope"].endswith(":read")
    assert by_name["authenticate"]["required_scope"].endswith(":write")
    assert by_name["register_token"]["required_scope"].endswith(":write")


# ── /mcp/tools/call — tool exempt (sem token) ─────────────────────────────────
def test_call_exempt_status_without_token(client: TestClient):
    r = client.post("/mcp/tools/call", json={"params": {"name": "status", "arguments": {}}})
    assert r.status_code == 200
    text = r.json()["result"]["content"][0]["text"]
    assert json.loads(text)["status"] == "ok"


# ── /mcp/tools/call — sem inner token → 401 ───────────────────────────────────
def test_call_missing_twin_token(client: TestClient):
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "whoami", "arguments": {}}},
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
        json={"params": {"name": "whoami", "arguments": {}, "_meta": {"twin_token": "tok"}}},
    )
    assert r.status_code == 401
    assert r.json()["error"] == "invalid_twin_token"


# ── /mcp/tools/call — token válido injeta tenant das claims (INV-3) ────────────
def test_call_valid_token_injects_tenant_from_claims(client: TestClient, monkeypatch):
    captured: dict = {}

    monkeypatch.setattr(M, "_verify_inner_token", lambda _t, _s: {"tenant_id": "T-42", "jti": "j"})

    def _spy(name, args, settings):
        captured["name"] = name
        captured["args"] = dict(args)
        return {"ok": True}

    monkeypatch.setattr(M, "_dispatch", _spy)
    r = client.post(
        "/mcp/tools/call",
        json={
            "params": {
                "name": "whoami",
                # tenant do cliente deve ser IGNORADO/sobrescrito pelas claims
                "arguments": {"tenant_id": "ATTACKER"},
                "_meta": {"twin_token": "tok"},
            }
        },
    )
    assert r.status_code == 200
    assert captured["name"] == "whoami"
    assert captured["args"]["tenant_id"] == "T-42"  # das claims, não "ATTACKER"


# ── /mcp/tools/call — token sem tenant nas claims → 401 ───────────────────────
def test_call_valid_token_without_tenant(client: TestClient, monkeypatch):
    monkeypatch.setattr(M, "_verify_inner_token", lambda _t, _s: {"jti": "j"})
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "whoami", "arguments": {}, "_meta": {"twin_token": "t"}}},
    )
    assert r.status_code == 401
    assert r.json()["error"] == "missing_tenant_scope"


# ── /mcp/tools/call — denylist (register/rotate retornam segredo) → 403 ───────
def test_call_excluded_register_token(client: TestClient):
    # excluída ANTES da verificação de token (fail-safe): 403 mesmo sem twin_token.
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "register_token", "arguments": {}}},
    )
    assert r.status_code == 403
    assert r.json()["error"] == "tool_excluded"


def test_call_excluded_rotate_token(client: TestClient):
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "rotate_token", "arguments": {}}},
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


# ── /mcp/tools/call — fluxo real de authenticate (store fake) ─────────────────
def test_call_authenticate_end_to_end(client: TestClient, settings, monkeypatch):
    monkeypatch.setattr(M, "_verify_inner_token", lambda _t, _s: {"tenant_id": "T", "jti": "j"})
    store = M._get_store(settings)
    reg = store.register(name="Dave", email="dave@test.com")
    r = client.post(
        "/mcp/tools/call",
        json={
            "params": {
                "name": "authenticate",
                "arguments": {"token": reg["token"]},
                "_meta": {"twin_token": "tok"},
            }
        },
    )
    assert r.status_code == 200
    payload = json.loads(r.json()["result"]["content"][0]["text"])
    assert payload["authenticated"] is True
    assert payload["name"] == "Dave"


# ── /mcp/tools/call — erro interno no dispatch → payload internal_error ────────
def test_call_internal_error(client: TestClient, monkeypatch):
    monkeypatch.setattr(M, "_verify_inner_token", lambda _t, _s: {"tenant_id": "T"})

    def _boom(_name, _args, _settings):
        raise ValueError("db exploded")

    monkeypatch.setattr(M, "_dispatch", _boom)
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "whoami", "arguments": {}, "_meta": {"twin_token": "t"}}},
    )
    assert r.status_code == 200
    payload = json.loads(r.json()["result"]["content"][0]["text"])
    assert payload["error"] == "internal_error"


# ── _dispatch cobre todas as tools + KeyError ─────────────────────────────────
def test_dispatch_status():
    assert M._dispatch("status", {}, _settings())["status"] == "ok"


def test_dispatch_session_flow(settings):
    store = M._get_store(settings)
    reg = store.register(name="Alice", email="alice@test.com")
    assert M._dispatch("authenticate", {"token": reg["token"]}, settings)["authenticated"] is True
    assert M._dispatch("whoami", {}, settings)["name"] == "Alice"
    assert M._dispatch("get_twin_context", {}, settings)["authenticated"] is True
    assert M._dispatch("context_status", {}, settings)["authenticated"] is True
    assert M._dispatch("refresh_context", {}, settings)["success"] is True


def test_dispatch_admin_flow(settings):
    store = M._get_store(settings)
    reg = M._dispatch(
        "register_token",
        {"admin_token": "admin-secret", "name": "Carol", "email": "carol@test.com"},
        settings,
    )
    assert reg["success"] is True
    listed = M._dispatch("list_tokens", {"admin_token": "admin-secret"}, settings)
    assert listed["count"] >= 1
    rot = M._dispatch(
        "rotate_token",
        {"admin_token": "admin-secret", "identifier": reg["user_id"]},
        settings,
    )
    assert rot["success"] is True
    rev = M._dispatch(
        "revoke_token",
        {"admin_token": "admin-secret", "identifier": rot["user_id"]},
        settings,
    )
    assert rev["success"] is True
    # store deve ter sido usado (mesma instância cacheada)
    assert store is M._get_store(settings)


def test_dispatch_unknown_raises(settings):
    with pytest.raises(KeyError):
        M._dispatch("does_not_exist", {}, settings)


# ── _verify_inner_token não configurado → PermissionError (fail-closed) ────────
def test_verify_inner_token_unconfigured():
    s = DevTwinSettings(MCP_TWIN_AUDIENCE="", URL_ADMIN_TWIN_JWKS="")
    with pytest.raises(PermissionError):
        M._verify_inner_token("tok", s)


# ── build_server smoke (cobre a fábrica + stdio Server) ───────────────────────
def test_build_server_smoke(monkeypatch):
    monkeypatch.delenv("MCP_TWIN_AUDIENCE", raising=False)
    from src.config import settings as settings_mod

    settings_mod.get_settings.cache_clear()
    server, settings, http_app = M.build_server()
    assert server is not None
    assert settings.mcp_twin_audience == "mcp:dev-twin-mcp"
    assert http_app.title.startswith("dev-twin-mcp")


# ── main(): branch HTTP-only e branch stdio ───────────────────────────────────
def test_main_http_only(monkeypatch):
    monkeypatch.setenv("MCP_HTTP_ONLY", "1")
    monkeypatch.delenv("MCP_TWIN_AUDIENCE", raising=False)
    from src.config import settings as settings_mod

    settings_mod.get_settings.cache_clear()
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
