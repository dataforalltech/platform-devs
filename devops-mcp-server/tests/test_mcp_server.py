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
        MCP_TWIN_AUDIENCE="mcp:devops-mcp",
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
    assert body == {"status": "ok", "service": "devops-mcp", "tools": 5}


# ── /mcp/tools/list — todos os 4 campos de policy (CI-2) ──────────────────────
def test_tools_list_has_policy_fields(client: TestClient):
    r = client.get("/mcp/tools/list")
    assert r.status_code == 200
    tools = r.json()["result"]["tools"]
    assert {t["name"] for t in tools} == {
        "status",
        "generate_kubernetes_manifest",
        "generate_dockerfile",
        "generate_github_actions_pipeline",
        "generate_helm_chart",
    }
    for t in tools:
        assert t["inputSchema"]["type"] == "object"
        for field in ("capability", "required_scope", "resource_type", "data_domain"):
            assert t[field], f"{t['name']} sem {field}"
        # required_scope no formato dominio:tipo:acao
        assert t["required_scope"].count(":") == 2
        # capability é o id estável <namespace>.<tool>
        assert t["capability"] == f"devops-mcp.{t['name']}"
    # geradores usam verbo :write; status é :read
    by_name = {t["name"]: t for t in tools}
    assert by_name["generate_dockerfile"]["required_scope"].endswith(":write")
    assert by_name["generate_kubernetes_manifest"]["required_scope"].endswith(":write")
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
        json={"params": {"name": "generate_dockerfile", "arguments": {"application": "X"}}},
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
                "name": "generate_dockerfile",
                "arguments": {"application": "X"},
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
                "name": "generate_dockerfile",
                # tenant do cliente deve ser IGNORADO/sobrescrito pelas claims
                "arguments": {"application": "X", "tenant_id": "ATTACKER"},
                "_meta": {"twin_token": "tok"},
            }
        },
    )
    assert r.status_code == 200
    assert captured["name"] == "generate_dockerfile"
    assert captured["args"]["tenant_id"] == "T-42"  # das claims, não "ATTACKER"


# ── /mcp/tools/call — token válido de fato executa a tool (integração) ────────
def test_call_valid_token_executes_tool(client: TestClient, monkeypatch):
    monkeypatch.setattr(M, "_verify_inner_token", lambda _t, _s: {"tenant_id": "T-9", "jti": "j"})
    r = client.post(
        "/mcp/tools/call",
        json={
            "params": {
                "name": "generate_kubernetes_manifest",
                "arguments": {"application": "billing", "replicas": 7},
                "_meta": {"twin_token": "tok"},
            }
        },
    )
    assert r.status_code == 200
    payload = json.loads(r.json()["result"]["content"][0]["text"])
    assert payload["application"] == "billing"
    assert payload["replicas"] == 7
    assert payload["manifests"]["deployment"]["spec"]["replicas"] == 7


# ── /mcp/tools/call — token sem tenant nas claims → 401 ───────────────────────
def test_call_valid_token_without_tenant(client: TestClient, monkeypatch):
    monkeypatch.setattr(M, "_verify_inner_token", lambda _t, _s: {"jti": "j"})
    r = client.post(
        "/mcp/tools/call",
        json={
            "params": {
                "name": "generate_dockerfile",
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


# ── /mcp/tools/call — erro interno da tool vira payload internal_error ─────────
def test_call_internal_error_is_captured(client: TestClient, monkeypatch):
    monkeypatch.setattr(M, "_verify_inner_token", lambda _t, _s: {"tenant_id": "T"})

    def _boom(_name, _args):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(M, "_dispatch", _boom)
    r = client.post(
        "/mcp/tools/call",
        json={
            "params": {
                "name": "generate_dockerfile",
                "arguments": {},
                "_meta": {"twin_token": "t"},
            }
        },
    )
    assert r.status_code == 200
    payload = json.loads(r.json()["result"]["content"][0]["text"])
    assert payload["error"] == "internal_error"
    assert payload["detail"] == "kaboom"


# ── /mcp/tools/call — body sem envelope 'params' (fallback body) ──────────────
def test_call_body_without_params_envelope(client: TestClient):
    # params default = body inteiro; status é exempt e não exige token.
    r = client.post("/mcp/tools/call", json={"name": "status", "arguments": {}})
    assert r.status_code == 200
    text = r.json()["result"]["content"][0]["text"]
    assert json.loads(text)["status"] == "ok"


# ── _dispatch cobre as 5 tools + KeyError ─────────────────────────────────────
def test_dispatch_routes_all_tools():
    assert M._dispatch("status", {})["status"] == "ok"
    km = M._dispatch("generate_kubernetes_manifest", {"application": "S", "replicas": 2})
    assert "manifests" in km
    assert km["replicas"] == 2
    df = M._dispatch("generate_dockerfile", {"application": "S", "runtime": "node:20"})
    assert df["runtime"] == "node:20"
    gh = M._dispatch("generate_github_actions_pipeline", {"application": "S"})
    assert "stages" in gh
    hc = M._dispatch("generate_helm_chart", {"app_name": "S"})
    assert hc["app_name"] == "S"
    with pytest.raises(KeyError):
        M._dispatch("unknown", {})


# ── _dispatch aplica defaults quando args ausentes ────────────────────────────
def test_dispatch_uses_defaults_when_args_missing():
    km = M._dispatch("generate_kubernetes_manifest", {})
    assert km["application"] == "app"
    assert km["replicas"] == 3
    df = M._dispatch("generate_dockerfile", {})
    assert df["application"] == "app"
    assert df["runtime"] == "python:3.11"
    gh = M._dispatch("generate_github_actions_pipeline", {})
    assert gh["application"] == "app"
    hc = M._dispatch("generate_helm_chart", {})
    assert hc["app_name"] == "app"


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
    assert settings.mcp_twin_audience == "mcp:devops-mcp"
    assert http_app.title.startswith("devops-mcp")


# ── stdio Server: handler list_tools espelha os 5 schemas ─────────────────────
def test_stdio_list_tools_handler():
    import asyncio

    from mcp.types import ListToolsRequest

    from src.config import settings as settings_mod

    settings_mod.get_settings.cache_clear()
    server, _settings, _http = M.build_server()
    handler = server.request_handlers[ListToolsRequest]
    result = asyncio.run(handler(ListToolsRequest(method="tools/list")))
    names = {t.name for t in result.root.tools}
    assert names == set(M._TOOL_SCHEMAS)


# ── stdio Server: handler call_tool despacha, unknown e erro interno ──────────
def test_stdio_call_tool_handler_success_and_errors(monkeypatch):
    import asyncio

    from mcp.types import CallToolRequest, CallToolRequestParams

    from src.config import settings as settings_mod

    settings_mod.get_settings.cache_clear()
    server, _settings, _http = M.build_server()
    handler = server.request_handlers[CallToolRequest]

    def _call(name, arguments):
        req = CallToolRequest(
            method="tools/call",
            params=CallToolRequestParams(name=name, arguments=arguments),
        )
        result = asyncio.run(handler(req))
        return json.loads(result.root.content[0].text)

    # success path
    assert _call("status", {})["status"] == "ok"
    # KeyError → unknown_tool (o handler stdio devolve payload, não HTTP 404)
    assert _call("nope", {}) == {"error": "unknown_tool", "tool": "nope"}
    # exceção genérica → internal_error
    monkeypatch.setattr(M, "_dispatch", lambda *_a: (_ for _ in ()).throw(RuntimeError("boom")))
    err = _call("generate_dockerfile", {})
    assert err["error"] == "internal_error"
    assert err["detail"] == "boom"
