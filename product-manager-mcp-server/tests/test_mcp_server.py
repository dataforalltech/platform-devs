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
        MCP_TWIN_AUDIENCE="mcp:product-manager-mcp",
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
    assert body == {"status": "ok", "service": "product-manager-mcp", "tools": 5}


# ── /mcp/tools/list — todos os 4 campos de policy (CI-2) ──────────────────────
def test_tools_list_has_policy_fields(client: TestClient):
    r = client.get("/mcp/tools/list")
    assert r.status_code == 200
    tools = r.json()["result"]["tools"]
    assert {t["name"] for t in tools} == {
        "generate_feature_spec",
        "generate_go_to_market_brief",
        "define_product_vision",
        "generate_release_plan",
        "status",
    }
    for t in tools:
        assert t["inputSchema"]["type"] == "object"
        for field in ("capability", "required_scope", "resource_type", "data_domain"):
            assert t[field], f"{t['name']} sem {field}"
        # required_scope no formato dominio:tipo:acao
        assert t["required_scope"].count(":") == 2
        # capability é o id estável <namespace>.<tool>
        assert t["capability"] == f"product-manager-mcp.{t['name']}"
    # geradores usam verbo :write; status é :read
    by_name = {t["name"]: t for t in tools}
    assert by_name["generate_feature_spec"]["required_scope"].endswith(":write")
    assert by_name["generate_go_to_market_brief"]["required_scope"].endswith(":write")
    assert by_name["define_product_vision"]["required_scope"].endswith(":write")
    assert by_name["generate_release_plan"]["required_scope"].endswith(":write")
    assert by_name["status"]["required_scope"].endswith(":read")


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
        json={"params": {"name": "generate_feature_spec", "arguments": {"feature": "X"}}},
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
                "name": "generate_feature_spec",
                "arguments": {"feature": "X"},
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
                "name": "generate_feature_spec",
                # tenant do cliente deve ser IGNORADO/sobrescrito pelas claims
                "arguments": {"feature": "X", "tenant_id": "ATTACKER"},
                "_meta": {"twin_token": "tok"},
            }
        },
    )
    assert r.status_code == 200
    assert captured["name"] == "generate_feature_spec"
    assert captured["args"]["tenant_id"] == "T-42"  # das claims, não "ATTACKER"


# ── /mcp/tools/call — token válido, dispatch real (happy path completo) ────────
def test_call_valid_token_real_dispatch(client: TestClient, monkeypatch):
    monkeypatch.setattr(M, "_verify_inner_token", lambda _t, _s: {"tenant_id": "T-9", "jti": "j"})
    r = client.post(
        "/mcp/tools/call",
        json={
            "params": {
                "name": "generate_feature_spec",
                "arguments": {"feature": "Dark Mode", "objective": "Reduce eye strain"},
                "_meta": {"twin_token": "tok"},
            }
        },
    )
    assert r.status_code == 200
    payload = json.loads(r.json()["result"]["content"][0]["text"])
    assert payload["feature"] == "Dark Mode"
    assert payload["objective"] == "Reduce eye strain"


# ── /mcp/tools/call — token sem tenant nas claims → 401 ───────────────────────
def test_call_valid_token_without_tenant(client: TestClient, monkeypatch):
    monkeypatch.setattr(M, "_verify_inner_token", lambda _t, _s: {"jti": "j"})
    r = client.post(
        "/mcp/tools/call",
        json={
            "params": {
                "name": "generate_feature_spec",
                "arguments": {},
                "_meta": {"twin_token": "t"},
            }
        },
    )
    assert r.status_code == 401
    assert r.json()["error"] == "missing_tenant_scope"


# ── /mcp/tools/call — denylist (exclude) → 403 ────────────────────────────────
def test_call_excluded_tool(client: TestClient, monkeypatch):
    monkeypatch.setattr(M, "_EXCLUDE_TOOLS", frozenset({"status"}))
    r = client.post("/mcp/tools/call", json={"params": {"name": "status", "arguments": {}}})
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


# ── /mcp/tools/call — erro interno da tool → payload com error (não 500) ──────
def test_call_tool_internal_error_is_captured(client: TestClient, monkeypatch):
    monkeypatch.setattr(M, "_verify_inner_token", lambda _t, _s: {"tenant_id": "T"})

    def _boom(_name, _args):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(M, "_dispatch", _boom)
    r = client.post(
        "/mcp/tools/call",
        json={
            "params": {
                "name": "generate_feature_spec",
                "arguments": {},
                "_meta": {"twin_token": "t"},
            }
        },
    )
    assert r.status_code == 200
    payload = json.loads(r.json()["result"]["content"][0]["text"])
    assert payload["error"] == "internal_error"
    assert payload["tool"] == "generate_feature_spec"


# ── _dispatch cobre as 5 tools + KeyError ─────────────────────────────────────
def test_dispatch_routes_all_tools():
    assert M._dispatch("status", {})["status"] == "ok"
    assert M._dispatch("generate_feature_spec", {"feature": "S"})["title"] == "Feature Spec: S"
    assert "target_segment" in M._dispatch("generate_go_to_market_brief", {})
    assert "vision" in M._dispatch("define_product_vision", {})
    assert "phases" in M._dispatch("generate_release_plan", {})
    with pytest.raises(KeyError):
        M._dispatch("unknown", {})


# ── _verify_inner_token não configurado → PermissionError (fail-closed) ────────
def test_verify_inner_token_unconfigured():
    s = Settings(MCP_TWIN_AUDIENCE="", URL_ADMIN_TWIN_JWKS="")
    with pytest.raises(PermissionError):
        M._verify_inner_token("tok", s)


# ── build_server smoke (cobre a fábrica + stdio Server) ───────────────────────
def test_build_server_smoke(monkeypatch):
    monkeypatch.delenv("MCP_TWIN_AUDIENCE", raising=False)
    from src.config import settings as settings_mod

    settings_mod.get_settings.cache_clear()
    server, settings, http_app = M.build_server()
    assert server is not None
    assert settings.mcp_twin_audience == "mcp:product-manager-mcp"
    assert http_app.title.startswith("product-manager-mcp")


# ── stdio Server handlers (list_tools/call_tool) — cobre o caminho MCP nativo ──
def test_stdio_server_handlers(monkeypatch):
    import asyncio

    monkeypatch.delenv("MCP_TWIN_AUDIENCE", raising=False)
    from src.config import settings as settings_mod

    settings_mod.get_settings.cache_clear()
    server, _settings, _http = M.build_server()

    # os handlers ficam registrados no request_handlers do Server MCP
    from mcp.types import CallToolRequest, ListToolsRequest

    async def _drive():
        list_handler = server.request_handlers[ListToolsRequest]
        tools_result = await list_handler(ListToolsRequest(method="tools/list"))
        names = {t.name for t in tools_result.root.tools}

        call_handler = server.request_handlers[CallToolRequest]
        ok = await call_handler(
            CallToolRequest(
                method="tools/call",
                params={"name": "status", "arguments": {}},
            )
        )
        bad = await call_handler(
            CallToolRequest(
                method="tools/call",
                params={"name": "does_not_exist", "arguments": {}},
            )
        )
        return names, ok, bad

    names, ok, bad = asyncio.run(_drive())
    assert names == {
        "generate_feature_spec",
        "generate_go_to_market_brief",
        "define_product_vision",
        "generate_release_plan",
        "status",
    }
    ok_text = ok.root.content[0].text
    assert json.loads(ok_text)["status"] == "ok"
    bad_text = bad.root.content[0].text
    assert json.loads(bad_text)["error"] == "unknown_tool"
