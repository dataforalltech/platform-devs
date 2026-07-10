"""Testes do sidecar mcp_http + PEP inner-token (STD-MCP-001 / STD-SEC-006).

Cobre: /v1/health, /mcp/tools/list (campos de policy), /mcp/tools/call
(missing/invalid token, exempt, tenant das claims, exclude, unknown, happy path,
erro interno), _dispatch e _verify_inner_token. O PyJWKClient/JWKS é sempre
mockado e o PostgreSQL é substituído pela camada SQLite in-memory do conftest —
os testes nunca fazem I/O de rede/DB (FID-01 / Test Doubles Policy).
"""

from __future__ import annotations

import datetime
import json
from decimal import Decimal

import psycopg2.pool
import pytest
from fastapi.testclient import TestClient

from src.config.settings import Settings
from src.server import mcp_server as M

from .conftest import _FakePool

_EXPECTED_TOOLS = {
    "create_test_plan",
    "get_test_plan",
    "list_test_plans",
    "generate_scenarios",
    "add_scenario",
    "record_result",
    "create_checklist",
    "run_checklist",
    "check_item",
    "add_bug",
    "double_check",
    "get_validation_status",
}


def _settings() -> Settings:
    return Settings(
        MCP_TWIN_AUDIENCE="mcp:test-mcp",
        URL_ADMIN_TWIN_JWKS="http://admin.local/.well-known/jwks.json",
    )


@pytest.fixture()
def client(store: M.TestStore) -> TestClient:
    """Sidecar HTTP com o ``store`` SQLite-backed do conftest."""
    return TestClient(M._build_http_app(_settings(), store))


# ── /v1/health ────────────────────────────────────────────────────────────────
def test_health(client: TestClient):
    r = client.get("/v1/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "service": "test-mcp", "tools": 12}


# ── /mcp/tools/list — todos os 4 campos de policy (CI-2) ──────────────────────
def test_tools_list_has_policy_fields(client: TestClient):
    r = client.get("/mcp/tools/list")
    assert r.status_code == 200
    tools = r.json()["result"]["tools"]
    assert {t["name"] for t in tools} == _EXPECTED_TOOLS
    for t in tools:
        assert t["inputSchema"]["type"] == "object"
        for field in ("capability", "required_scope", "resource_type", "data_domain"):
            assert t[field], f"{t['name']} sem {field}"
        assert t["required_scope"].count(":") == 2  # dominio:tipo:acao
        assert t["capability"] == f"test-mcp.{t['name']}"
        assert t["required_scope"].startswith("test-mcp:")
    by_name = {t["name"]: t for t in tools}
    assert by_name["create_test_plan"]["required_scope"].endswith(":write")
    assert by_name["add_bug"]["required_scope"].endswith(":write")
    assert by_name["record_result"]["required_scope"].endswith(":write")
    assert by_name["get_test_plan"]["required_scope"].endswith(":read")
    assert by_name["double_check"]["required_scope"].endswith(":read")


# ── /mcp/tools/call — sem inner token → 401 ───────────────────────────────────
def test_call_missing_twin_token(client: TestClient):
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "list_test_plans", "arguments": {}}},
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
                "name": "list_test_plans",
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

    def _spy(name, args, _store):
        captured["name"] = name
        captured["args"] = dict(args)
        return {"ok": True}

    monkeypatch.setattr(M, "_dispatch", _spy)
    r = client.post(
        "/mcp/tools/call",
        json={
            "params": {
                "name": "list_test_plans",
                # tenant do cliente deve ser IGNORADO/sobrescrito pelas claims
                "arguments": {"tenant_id": "ATTACKER"},
                "_meta": {"twin_token": "tok"},
            }
        },
    )
    assert r.status_code == 200
    assert captured["name"] == "list_test_plans"
    assert captured["args"]["tenant_id"] == "T-42"  # das claims, não "ATTACKER"


# ── /mcp/tools/call — token sem tenant nas claims → 401 ───────────────────────
def test_call_valid_token_without_tenant(client: TestClient, monkeypatch):
    monkeypatch.setattr(M, "_verify_inner_token", lambda _t, _s: {"jti": "j"})
    r = client.post(
        "/mcp/tools/call",
        json={
            "params": {
                "name": "list_test_plans",
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
                "name": "create_test_plan",
                "arguments": {"title": "P", "scope": "S"},
                "_meta": {"twin_token": "tok"},
            }
        },
    )
    assert r.status_code == 200
    payload = json.loads(r.json()["result"]["content"][0]["text"])
    # tenant_id injetado foi removido pelo dispatcher → a tool executou com sucesso
    assert payload["title"] == "P"
    assert payload["status"] == "active"


# ── /mcp/tools/call — tool exempt (sem token) via monkeypatch ─────────────────
def test_call_exempt_tool_without_token(client: TestClient, monkeypatch):
    monkeypatch.setattr(M, "_EXEMPT_TOOLS", frozenset({"list_test_plans"}))
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "list_test_plans", "arguments": {}}},
    )
    assert r.status_code == 200
    payload = json.loads(r.json()["result"]["content"][0]["text"])
    assert "count" in payload


# ── /mcp/tools/call — denylist (exclude) → 403 ────────────────────────────────
def test_call_excluded_tool(client: TestClient, monkeypatch):
    monkeypatch.setattr(M, "_EXCLUDE_TOOLS", frozenset({"list_test_plans"}))
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "list_test_plans", "arguments": {}}},
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

    def _boom(name, args, _store):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(M, "_dispatch", _boom)
    r = client.post(
        "/mcp/tools/call",
        json={
            "params": {
                "name": "list_test_plans",
                "arguments": {},
                "_meta": {"twin_token": "t"},
            }
        },
    )
    assert r.status_code == 200
    payload = json.loads(r.json()["result"]["content"][0]["text"])
    assert payload["error"] == "internal_error"
    assert "kaboom" in payload["detail"]


# ── _dispatch cobre roteamento + KeyError + strip de tenant + TypeError ────────
def test_dispatch_routes_and_strips_tenant(store: M.TestStore):
    plan = M._dispatch("create_test_plan", {"title": "P", "scope": "S", "tenant_id": "T"}, store)
    assert plan["title"] == "P"  # tenant_id removido, não vira invalid_arguments
    listed = M._dispatch("list_test_plans", {}, store)
    assert listed["count"] >= 1
    add = M._dispatch(
        "add_bug", {"plan_id": str(plan["id"]), "severity": "low", "title": "t", "description": "d"}, store
    )
    assert add["severity"] == "low"  # add_bug → validation_tool.add_finding
    with pytest.raises(KeyError):
        M._dispatch("unknown", {}, store)


def test_dispatch_invalid_arguments(store: M.TestStore):
    result = M._dispatch("list_test_plans", {"bogus": 1}, store)
    assert result["error"] == "invalid_arguments"


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
    assert captured["audience"] == "mcp:test-mcp"
    assert set(captured["options"]["require"]) == {"exp", "aud", "jti"}


# ── build_server smoke (cobre a fábrica + stdio Server; pool faked) ───────────
def test_build_server_smoke(monkeypatch):
    monkeypatch.setattr(psycopg2.pool, "ThreadedConnectionPool", _FakePool)
    from src.config import settings as settings_mod

    settings_mod.get_settings.cache_clear()
    server, settings, store, http_app = M.build_server()
    assert server is not None
    assert settings.mcp_twin_audience == "mcp:test-mcp"
    assert http_app.title.startswith("test-mcp")
    resp = TestClient(http_app).get("/v1/health")
    assert resp.json()["service"] == "test-mcp"
    store.close()
    settings_mod.get_settings.cache_clear()


# ── _JSONEncoder serializa datetime/Decimal (retornos do psycopg2) ────────────
def test_json_encoder_serializes_datetime_and_decimal():
    payload = {
        "when": datetime.datetime(2026, 1, 2, 3, 4, 5),
        "day": datetime.date(2026, 1, 2),
        "amount": Decimal("12.50"),
    }
    out = json.loads(json.dumps(payload, cls=M._JSONEncoder))
    assert out["when"].startswith("2026-01-02T03:04:05")
    assert out["day"] == "2026-01-02"
    assert out["amount"] == 12.5


def test_json_encoder_raises_on_unknown_type():
    with pytest.raises(TypeError):
        json.dumps({"x": object()}, cls=M._JSONEncoder)


# ── stdio handlers registrados no low-level Server (list_tools / call_tool) ────
def _find_handler(server, needle: str):
    for req_type, fn in server.request_handlers.items():
        if needle in req_type.__name__.lower():
            return fn
    raise AssertionError(f"handler {needle} não encontrado")


@pytest.fixture()
def built(monkeypatch):
    monkeypatch.setattr(psycopg2.pool, "ThreadedConnectionPool", _FakePool)
    from src.config import settings as settings_mod

    settings_mod.get_settings.cache_clear()
    result = M.build_server()
    yield result
    result[2].close()  # store.close()
    settings_mod.get_settings.cache_clear()


async def test_stdio_list_tools(built):
    from mcp import types

    server = built[0]
    fn = _find_handler(server, "listtools")
    result = await fn(types.ListToolsRequest(method="tools/list"))
    tools = result.root.tools
    assert {t.name for t in tools} == _EXPECTED_TOOLS
    assert all(t.inputSchema["type"] == "object" for t in tools)


async def _invoke_call(server, name, arguments):
    from mcp import types

    fn = _find_handler(server, "calltool")
    req = types.CallToolRequest(
        method="tools/call",
        params=types.CallToolRequestParams(name=name, arguments=arguments),
    )
    result = await fn(req)
    return json.loads(result.root.content[0].text)


async def test_stdio_call_tool_happy_and_errors(built, monkeypatch):
    server = built[0]
    plan = await _invoke_call(server, "create_test_plan", {"title": "P", "scope": "S"})
    assert plan["title"] == "P"
    # tool desconhecida → unknown_tool (KeyError capturado no handler stdio)
    unknown = await _invoke_call(server, "does_not_exist", {})
    assert unknown["error"] == "unknown_tool"
    # erro interno propaga como internal_error
    monkeypatch.setattr(M, "_dispatch", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    err = await _invoke_call(server, "list_test_plans", {})
    assert err["error"] == "internal_error"
    assert "boom" in err["detail"]


# ── main() com MCP_HTTP_ONLY=1 → sobe só o sidecar (uvicorn.run mockado) ───────
def test_main_http_only(monkeypatch):
    monkeypatch.setenv("MCP_HTTP_ONLY", "1")
    ran: dict = {}

    class _FakeHttp:
        title = "test-mcp API"

    monkeypatch.setattr(M, "build_server", lambda: (None, _settings(), None, _FakeHttp()))

    import uvicorn

    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: ran.setdefault("called", True))
    M.main()
    assert ran["called"] is True
