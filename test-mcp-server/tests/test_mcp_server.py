"""Testes do sidecar mcp_http + PEP inner-token (STD-MCP-001 / STD-SEC-006).

Cobre: /v1/health, /mcp/tools/list (campos de policy), /mcp/tools/call
(missing/invalid token, tenant das claims, exclude, unknown, happy path, erro
interno), o dispatcher async, _verify_inner_token e o caminho credencial-zero real
(_run_tool -> for_tenant -> store) contra MySQL. RS256 é sempre real (chave gerada +
PyJWKClient servindo a chave pública local) — nunca bypass.
"""

from __future__ import annotations

import datetime
import json
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from src.config.settings import Settings
from src.server import mcp_server as M

from .conftest import mint_token, patch_jwks, requires_mysql

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
def client() -> TestClient:
    """Sidecar HTTP (sem store global; a persistência é resolvida por-request)."""
    return TestClient(M._build_http_app(_settings()))


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
        json={"params": {"name": "list_test_plans", "arguments": {}, "_meta": {"twin_token": "tok"}}},
    )
    assert r.status_code == 401
    assert r.json()["error"] == "invalid_twin_token"


# ── /mcp/tools/call — token sem tenant nas claims → 401 ───────────────────────
def test_call_valid_token_without_tenant(client: TestClient, monkeypatch):
    monkeypatch.setattr(M, "_verify_inner_token", lambda _t, _s: {"jti": "j"})
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "list_test_plans", "arguments": {}, "_meta": {"twin_token": "t"}}},
    )
    assert r.status_code == 401
    assert r.json()["error"] == "missing_tenant_scope"


# ── /mcp/tools/call — token válido: tenant das claims DIRIGE o pool (INV-3) ────
def test_call_tenant_from_claims_drives_pool(client: TestClient, monkeypatch):
    captured: dict = {}

    monkeypatch.setattr(M, "_verify_inner_token", lambda _t, _s: {"tenant_id": "T-42", "jti": "j"})

    async def _fake_run_tool(name, arguments, settings, tenant_id):
        captured["name"] = name
        captured["tenant_id"] = tenant_id
        captured["args"] = dict(arguments)
        return {"ok": True}

    monkeypatch.setattr(M, "_run_tool", _fake_run_tool)
    r = client.post(
        "/mcp/tools/call",
        json={
            "params": {
                "name": "list_test_plans",
                # tenant do cliente deve ser IGNORADO (tenant vem das claims).
                "arguments": {"tenant_id": "ATTACKER"},
                "_meta": {"twin_token": "tok"},
            }
        },
    )
    assert r.status_code == 200
    assert captured["name"] == "list_test_plans"
    assert captured["tenant_id"] == "T-42"  # das claims, não "ATTACKER"
    # o tenant NÃO é injetado nos args (dirige o pool, não a chamada da tool)
    assert captured["args"] == {"tenant_id": "ATTACKER"}


# ── /mcp/tools/call — happy path (RS256 real; _run_tool mockado) ──────────────
def test_call_happy_path_real_token(client: TestClient, monkeypatch, rsa_key):
    patch_jwks(monkeypatch, rsa_key)

    async def _fake_run_tool(name, arguments, settings, tenant_id):
        return {"title": arguments.get("title"), "status": "active"}

    monkeypatch.setattr(M, "_run_tool", _fake_run_tool)
    token = mint_token(rsa_key, tenant_id="T-1")
    r = client.post(
        "/mcp/tools/call",
        json={
            "params": {
                "name": "create_test_plan",
                "arguments": {"title": "P", "scope": "S"},
                "_meta": {"twin_token": token},
            }
        },
    )
    assert r.status_code == 200
    payload = json.loads(r.json()["result"]["content"][0]["text"])
    assert payload["title"] == "P"
    assert payload["status"] == "active"


# ── /mcp/tools/call — matriz do inner token via _verify_inner_token REAL ──────
# RS256 real (patch_jwks serve a chave pública); o PEP rejeita ANTES de tocar o DB,
# então estes negativos rodam sem MySQL. Sem monkeypatch-raise: a verificação é real.
def test_call_missing_jti_real_token(client: TestClient, monkeypatch, rsa_key):
    """Token válido porém SEM jti → require=['jti'] rejeita → 401 (JTI_REQUIRED)."""
    patch_jwks(monkeypatch, rsa_key)
    token = mint_token(rsa_key, tenant_id="T-1", include_jti=False)
    r = client.post(
        "/mcp/tools/call",
        json={
            "params": {
                "name": "list_test_plans",
                "arguments": {},
                "_meta": {"twin_token": token},
            }
        },
    )
    assert r.status_code == 401
    assert r.json()["error"] == "invalid_twin_token"


def test_call_wrong_audience_real_token(client: TestClient, monkeypatch, rsa_key):
    """Audiência divergente (mcp:errado) → 401 (a falha de integração nº 1)."""
    patch_jwks(monkeypatch, rsa_key)
    token = mint_token(rsa_key, tenant_id="T-1", aud="mcp:errado")
    r = client.post(
        "/mcp/tools/call",
        json={
            "params": {
                "name": "list_test_plans",
                "arguments": {},
                "_meta": {"twin_token": token},
            }
        },
    )
    assert r.status_code == 401
    assert r.json()["error"] == "invalid_twin_token"


def test_call_expired_real_token(client: TestClient, monkeypatch, rsa_key):
    """Token expirado (exp no passado) → 401 (ExpiredSignatureError, fail-closed)."""
    patch_jwks(monkeypatch, rsa_key)
    token = mint_token(rsa_key, tenant_id="T-1", exp_delta=-10)
    r = client.post(
        "/mcp/tools/call",
        json={
            "params": {
                "name": "list_test_plans",
                "arguments": {},
                "_meta": {"twin_token": token},
            }
        },
    )
    assert r.status_code == 401
    assert r.json()["error"] == "invalid_twin_token"


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

    async def _raise_key(name, arguments, settings, tenant_id):
        raise KeyError(name)

    monkeypatch.setattr(M, "_run_tool", _raise_key)
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "nope", "arguments": {}, "_meta": {"twin_token": "t"}}},
    )
    assert r.status_code == 404
    assert r.json()["error"] == "unknown_tool"


# ── /mcp/tools/call — erro interno → payload internal_error ────────────────────
def test_call_internal_error(client: TestClient, monkeypatch):
    monkeypatch.setattr(M, "_verify_inner_token", lambda _t, _s: {"tenant_id": "T"})

    async def _boom(name, arguments, settings, tenant_id):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(M, "_run_tool", _boom)
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "list_test_plans", "arguments": {}, "_meta": {"twin_token": "t"}}},
    )
    assert r.status_code == 200
    payload = json.loads(r.json()["result"]["content"][0]["text"])
    assert payload["error"] == "internal_error"
    assert "kaboom" in payload["detail"]


# ── _dispatch (async) roteia + KeyError + TypeError ───────────────────────────
async def test_dispatch_unknown_raises_keyerror():
    class _NoStore:
        pass

    with pytest.raises(KeyError):
        await M._dispatch("unknown", {}, _NoStore())  # type: ignore[arg-type]


async def test_dispatch_invalid_arguments(store):
    result = await M._dispatch("list_test_plans", {"bogus": 1}, store)
    assert result["error"] == "invalid_arguments"


# ── _verify_inner_token ───────────────────────────────────────────────────────
def test_verify_inner_token_unconfigured():
    s = Settings(MCP_TWIN_AUDIENCE="", URL_ADMIN_TWIN_JWKS="")
    with pytest.raises(PermissionError):
        M._verify_inner_token("tok", s)


def test_verify_inner_token_decodes(monkeypatch, rsa_key):
    s = _settings()
    patch_jwks(monkeypatch, rsa_key)
    token = mint_token(rsa_key, tenant_id="T", jti="j")
    claims = M._verify_inner_token(token, s)
    assert claims["tenant_id"] == "T"
    assert claims["aud"] == "mcp:test-mcp"


def test_verify_inner_token_rejects_wrong_audience(monkeypatch, rsa_key):
    s = _settings()
    patch_jwks(monkeypatch, rsa_key)
    token = mint_token(rsa_key, aud="mcp:outro-servico")
    with pytest.raises(Exception):  # noqa: B017 — audiência divergente rejeita (fail-closed)
        M._verify_inner_token(token, s)


# ── build_server smoke (fábrica + stdio Server; sem DB) ───────────────────────
def test_build_server_smoke(monkeypatch):
    monkeypatch.setenv("MCP_TWIN_AUDIENCE", "mcp:test-mcp")
    from src.config import settings as settings_mod

    settings_mod.get_settings.cache_clear()
    server, settings, http_app = M.build_server()
    assert server is not None
    assert settings.mcp_twin_audience == "mcp:test-mcp"
    assert http_app.title.startswith("test-mcp")
    resp = TestClient(http_app).get("/v1/health")
    assert resp.json()["service"] == "test-mcp"
    settings_mod.get_settings.cache_clear()


# ── _JSONEncoder serializa datetime/Decimal (colunas padrão do ORM) ───────────
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


# ── stdio handlers: list_tools + call_tool (gateway-only, fail-closed) ────────
def _find_handler(server, needle: str):
    for req_type, fn in server.request_handlers.items():
        if needle in req_type.__name__.lower():
            return fn
    raise AssertionError(f"handler {needle} não encontrado")


@pytest.fixture()
def built(monkeypatch):
    from src.config import settings as settings_mod

    settings_mod.get_settings.cache_clear()
    result = M.build_server()
    yield result
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


async def test_stdio_call_tool_is_gateway_only(built):
    server = built[0]
    # tool conhecida via stdio → recusa fail-closed (sem tenant; gateway-only)
    known = await _invoke_call(server, "create_test_plan", {"title": "P", "scope": "S"})
    assert known["error"] == "tenant_context_required"
    # tool desconhecida → unknown_tool
    unknown = await _invoke_call(server, "does_not_exist", {})
    assert unknown["error"] == "unknown_tool"


# ── main() com MCP_HTTP_ONLY=1 → sobe só o sidecar (uvicorn.run mockado) ───────
def test_main_http_only(monkeypatch):
    monkeypatch.setenv("MCP_HTTP_ONLY", "1")
    ran: dict = {}

    class _FakeHttp:
        title = "test-mcp API"

    monkeypatch.setattr(M, "build_server", lambda: (None, _settings(), _FakeHttp()))

    import uvicorn

    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: ran.setdefault("called", True))
    M.main()
    assert ran["called"] is True


# ── Caminho credencial-zero REAL: _run_tool -> for_tenant -> store (MySQL) ─────
@requires_mysql
@pytest.mark.integration
async def test_run_tool_end_to_end_real_tenant(seed_platforms):
    from .conftest import TENANT_A, _test_settings

    settings = _test_settings()
    payload = await M._run_tool("create_test_plan", {"title": "P", "scope": "S"}, settings, TENANT_A)
    assert payload["title"] == "P"
    assert payload["status"] == "active"
    assert isinstance(payload["id"], int) and payload["id"] > 0

    # segunda chamada reusa o guard _SCHEMA_READY (schema já garantido)
    listed = await M._run_tool("list_test_plans", {}, settings, TENANT_A)
    assert listed["count"] >= 1

    # tool desconhecida propaga KeyError (o handler HTTP o traduz p/ 404)
    with pytest.raises(KeyError):
        await M._run_tool("does_not_exist", {}, settings, TENANT_A)
