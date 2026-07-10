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

# Conjunto canônico das 12 tools expostas pelo security-mcp.
_TOOL_NAMES = {
    "review_secure_code",
    "scan_secrets",
    "scan_dependency_risks",
    "calculate_cvss",
    "harden_headers",
    "check_password_policy",
    "analyze_compliance",
    "map_attack_surface",
    "generate_threat_model",
    "generate_security_controls",
    "generate_incident_response_plan",
    "status",
}


def _settings() -> Settings:
    return Settings(
        MCP_TWIN_AUDIENCE="mcp:security-mcp",
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
    assert body == {"status": "ok", "service": "security-mcp", "tools": 12}


# ── /mcp/tools/list — todos os 4 campos de policy (CI-2) ──────────────────────
def test_tools_list_has_policy_fields(client: TestClient):
    r = client.get("/mcp/tools/list")
    assert r.status_code == 200
    tools = r.json()["result"]["tools"]
    assert {t["name"] for t in tools} == _TOOL_NAMES
    for t in tools:
        assert t["inputSchema"]["type"] == "object"
        for field in ("capability", "required_scope", "resource_type", "data_domain"):
            assert t[field], f"{t['name']} sem {field}"
        # required_scope no formato dominio:tipo:acao
        assert t["required_scope"].count(":") == 2
        # capability é o id estável <namespace>.<tool>
        assert t["capability"] == f"security-mcp.{t['name']}"
    # geradores usam verbo :write; status/análise usam :read
    by_name = {t["name"]: t for t in tools}
    assert by_name["generate_threat_model"]["required_scope"].endswith(":write")
    assert by_name["generate_incident_response_plan"]["required_scope"].endswith(":write")
    assert by_name["status"]["required_scope"].endswith(":read")
    assert by_name["scan_secrets"]["required_scope"].endswith(":read")


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
        json={"params": {"name": "review_secure_code", "arguments": {"code": "x = 1"}}},
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
                "name": "review_secure_code",
                "arguments": {"code": "x = 1"},
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
                "name": "scan_secrets",
                # tenant do cliente deve ser IGNORADO/sobrescrito pelas claims
                "arguments": {"content": "x", "tenant_id": "ATTACKER"},
                "_meta": {"twin_token": "tok"},
            }
        },
    )
    assert r.status_code == 200
    assert captured["name"] == "scan_secrets"
    assert captured["args"]["tenant_id"] == "T-42"  # das claims, não "ATTACKER"


# ── /mcp/tools/call — token sem tenant nas claims → 401 ───────────────────────
def test_call_valid_token_without_tenant(client: TestClient, monkeypatch):
    monkeypatch.setattr(M, "_verify_inner_token", lambda _t, _s: {"jti": "j"})
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "scan_secrets", "arguments": {}, "_meta": {"twin_token": "t"}}},
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


# ── /mcp/tools/call — token válido despacha e retorna payload real ────────────
def test_call_valid_token_dispatches_tool(client: TestClient, monkeypatch):
    monkeypatch.setattr(M, "_verify_inner_token", lambda _t, _s: {"tenant_id": "T-9"})
    r = client.post(
        "/mcp/tools/call",
        json={
            "params": {
                "name": "calculate_cvss",
                "arguments": {"vector": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"},
                "_meta": {"twin_token": "t"},
            }
        },
    )
    assert r.status_code == 200
    payload = json.loads(r.json()["result"]["content"][0]["text"])
    assert payload["base_score"] == 9.8
    assert payload["severity"] == "Critical"


# ── /mcp/tools/call — erro interno da tool vira payload de erro (não 500) ──────
def test_call_tool_internal_error_becomes_payload(client: TestClient, monkeypatch):
    monkeypatch.setattr(M, "_verify_inner_token", lambda _t, _s: {"tenant_id": "T"})

    def _boom(_name, _args):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(M, "_dispatch", _boom)
    r = client.post(
        "/mcp/tools/call",
        json={
            "params": {
                "name": "scan_secrets",
                "arguments": {},
                "_meta": {"twin_token": "t"},
            }
        },
    )
    assert r.status_code == 200
    payload = json.loads(r.json()["result"]["content"][0]["text"])
    assert payload["error"] == "internal_error"
    assert payload["detail"] == "kaboom"


# ── _dispatch cobre as 12 tools + KeyError ────────────────────────────────────
def test_dispatch_routes_all_tools():
    assert "issues" in M._dispatch("review_secure_code", {"code": "x = 1"})
    assert "findings" in M._dispatch("scan_secrets", {"content": "x"})
    assert "dependencies" in M._dispatch("scan_dependency_risks", {"manifest": "flask==2.0"})
    assert "base_score" in M._dispatch(
        "calculate_cvss", {"vector": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"}
    )
    assert "missing_headers" in M._dispatch("harden_headers", {})
    assert "standard" in M._dispatch("check_password_policy", {})
    assert "controls" in M._dispatch("analyze_compliance", {"framework": "owasp"})
    assert "risk_hotspots" in M._dispatch("map_attack_surface", {"system": "S"})
    assert "threats" in M._dispatch("generate_threat_model", {"system": "S"})
    assert "controls" in M._dispatch("generate_security_controls", {"system": "S"})
    assert "phases" in M._dispatch("generate_incident_response_plan", {})
    assert M._dispatch("status", {})["status"] == "ok"
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
    assert settings.mcp_twin_audience == "mcp:security-mcp"
    assert http_app.title.startswith("security-mcp")
