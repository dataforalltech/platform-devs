"""Testes do sidecar mcp_http + PEP inner-token (STD-MCP-001 / STD-SEC-006).

Cobre: /v1/health, /mcp/tools/list (campos de policy), /mcp/tools/call
(missing/invalid token, exempt, tenant das claims, exclude, unknown, internal),
_verify_inner_token não configurado e a fábrica build_server. O PyJWKClient/JWKS é
sempre mockado — os testes nunca fazem I/O de rede nem abrem um pool psycopg2
(FID-01 / Test Doubles Policy). O DocsStore é substituído pelo FakeDocsStore.
"""

from __future__ import annotations

import asyncio
import json

import mcp.types as mtypes
import pytest
from fastapi.testclient import TestClient

from src.config.settings import Settings
from src.server import mcp_server as M

from .conftest import FakeDocsStore


def _settings() -> Settings:
    return Settings(
        MCP_TWIN_AUDIENCE="mcp:docs-mcp",
        URL_ADMIN_TWIN_JWKS="http://admin.local/.well-known/jwks.json",
    )


@pytest.fixture()
def client() -> TestClient:
    return TestClient(M._build_http_app(_settings(), FakeDocsStore()))


# ── /v1/health ────────────────────────────────────────────────────────────────
def test_health(client: TestClient):
    r = client.get("/v1/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "service": "docs-mcp", "tools": 14}


# ── /mcp/tools/list — todos os 4 campos de policy (CI-2) ──────────────────────
def test_tools_list_has_policy_fields(client: TestClient):
    r = client.get("/mcp/tools/list")
    assert r.status_code == 200
    tools = r.json()["result"]["tools"]
    assert len(tools) == 14
    assert "scan_docs" in {t["name"] for t in tools}
    for t in tools:
        assert t["inputSchema"]["type"] == "object"
        for field in ("capability", "required_scope", "resource_type", "data_domain"):
            assert t[field], f"{t['name']} sem {field}"
        # required_scope no formato dominio:tipo:acao (3 segmentos)
        assert t["required_scope"].count(":") == 2
        assert t["capability"] == f"docs-mcp.{t['name']}"
    by_name = {t["name"]: t for t in tools}
    # geração de artefato usa verbo :write; análise/scan/validação é :read
    assert by_name["generate_doc"]["required_scope"].endswith(":write")
    assert by_name["scan_docs"]["required_scope"].endswith(":read")
    assert by_name["validate_doc"]["required_scope"].endswith(":read")


# ── /mcp/tools/call — sem inner token → 401 ───────────────────────────────────
def test_call_missing_twin_token(client: TestClient):
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "list_templates", "arguments": {}}},
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
                "name": "list_templates",
                "arguments": {},
                "_meta": {"twin_token": "tok"},
            }
        },
    )
    assert r.status_code == 401
    assert r.json()["error"] == "invalid_twin_token"


# ── /mcp/tools/call — tool exempt (sem token) ─────────────────────────────────
def test_call_exempt_tool_without_token(client: TestClient, monkeypatch):
    # docs-mcp não tem tool exempt por padrão; simula a whitelist p/ cobrir o ramo.
    monkeypatch.setattr(M, "_EXEMPT_TOOLS", frozenset({"list_templates"}))
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "list_templates", "arguments": {}}},
    )
    assert r.status_code == 200
    text = r.json()["result"]["content"][0]["text"]
    assert json.loads(text)["count"] == 6


# ── /mcp/tools/call — token válido injeta tenant das claims (INV-3) ────────────
def test_call_valid_token_injects_tenant_from_claims(client: TestClient, monkeypatch):
    captured: dict = {}

    monkeypatch.setattr(M, "_verify_inner_token", lambda _t, _s: {"tenant_id": "T-42", "jti": "j"})

    def _spy(name, args, settings, store):
        captured["name"] = name
        captured["args"] = dict(args)
        return {"ok": True}

    monkeypatch.setattr(M, "_dispatch", _spy)
    r = client.post(
        "/mcp/tools/call",
        json={
            "params": {
                "name": "scan_docs",
                # tenant do cliente deve ser IGNORADO/sobrescrito pelas claims
                "arguments": {"repo_path": "/x", "tenant_id": "ATTACKER"},
                "_meta": {"twin_token": "tok"},
            }
        },
    )
    assert r.status_code == 200
    assert captured["name"] == "scan_docs"
    assert captured["args"]["tenant_id"] == "T-42"  # das claims, não "ATTACKER"


# ── /mcp/tools/call — token sem tenant nas claims → 401 ───────────────────────
def test_call_valid_token_without_tenant(client: TestClient, monkeypatch):
    monkeypatch.setattr(M, "_verify_inner_token", lambda _t, _s: {"jti": "j"})
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "scan_docs", "arguments": {}, "_meta": {"twin_token": "t"}}},
    )
    assert r.status_code == 401
    assert r.json()["error"] == "missing_tenant_scope"


# ── /mcp/tools/call — denylist (exclude) → 403 ────────────────────────────────
def test_call_excluded_tool(client: TestClient, monkeypatch):
    monkeypatch.setattr(M, "_EXCLUDE_TOOLS", frozenset({"list_templates"}))
    r = client.post("/mcp/tools/call", json={"params": {"name": "list_templates", "arguments": {}}})
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


# ── /mcp/tools/call — erro interno no dispatch → payload internal_error ────────
def test_call_internal_error(client: TestClient, monkeypatch):
    monkeypatch.setattr(M, "_verify_inner_token", lambda _t, _s: {"tenant_id": "T"})

    def _boom(name, args, settings, store):
        raise RuntimeError("boom")

    monkeypatch.setattr(M, "_dispatch", _boom)
    r = client.post(
        "/mcp/tools/call",
        json={
            "params": {
                "name": "scan_docs",
                "arguments": {"repo_path": "/x"},
                "_meta": {"twin_token": "t"},
            }
        },
    )
    assert r.status_code == 200
    payload = json.loads(r.json()["result"]["content"][0]["text"])
    assert payload["error"] == "internal_error"
    assert "boom" in payload["detail"]


# ── _dispatch cobre roteamento básico + KeyError ──────────────────────────────
def test_dispatch_routes_list_templates():
    store = FakeDocsStore()
    assert M._dispatch("list_templates", {}, _settings(), store)["count"] == 6
    with pytest.raises(KeyError):
        M._dispatch("unknown", {}, _settings(), store)


# ── _verify_inner_token não configurado → PermissionError (fail-closed) ────────
def test_verify_inner_token_unconfigured():
    s = Settings(MCP_TWIN_AUDIENCE="", URL_ADMIN_TWIN_JWKS="")
    with pytest.raises(PermissionError):
        M._verify_inner_token("tok", s)


# ── build_server + stdio Server (fábrica + handlers de baixo nível MCP) ────────
@pytest.fixture()
def built(monkeypatch):
    monkeypatch.setattr(M, "DocsStore", lambda settings: FakeDocsStore())
    monkeypatch.delenv("MCP_TWIN_AUDIENCE", raising=False)
    from src.config import settings as settings_mod

    settings_mod.get_settings.cache_clear()
    return M.build_server()


def test_build_server_smoke(built):
    server, settings, store, http_app = built
    assert server is not None
    assert isinstance(store, FakeDocsStore)
    assert settings.mcp_twin_audience == "mcp:docs-mcp"
    assert http_app.title.startswith("docs-mcp")


def test_stdio_list_tools_handler(built):
    server = built[0]
    handler = server.request_handlers[mtypes.ListToolsRequest]
    res = asyncio.run(handler(mtypes.ListToolsRequest(method="tools/list")))
    assert len(res.root.tools) == 14


def test_stdio_call_tool_handler_ok(built):
    server = built[0]
    handler = server.request_handlers[mtypes.CallToolRequest]
    req = mtypes.CallToolRequest(
        method="tools/call",
        params=mtypes.CallToolRequestParams(name="list_templates", arguments={}),
    )
    res = asyncio.run(handler(req))
    assert "README" in res.root.content[0].text


def test_stdio_call_tool_handler_internal_error(built, monkeypatch):
    server = built[0]

    def _boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(M, "_dispatch", _boom)
    handler = server.request_handlers[mtypes.CallToolRequest]
    req = mtypes.CallToolRequest(
        method="tools/call",
        params=mtypes.CallToolRequestParams(name="scan_docs", arguments={"repo_path": "/x"}),
    )
    res = asyncio.run(handler(req))
    payload = json.loads(res.root.content[0].text)
    assert payload["error"] == "internal_error"
