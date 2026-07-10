"""Testes do sidecar mcp_http + PEP inner-token (STD-MCP-001 / STD-SEC-006).

Cobre: /v1/health, /mcp/tools/list (campos de policy), /mcp/tools/call
(missing/invalid token, exempt, tenant das claims, exclude, unknown) e
_verify_inner_token não configurado. O PyJWKClient/JWKS é sempre mockado —
os testes nunca fazem I/O de rede (FID-01 / Test Doubles Policy).

qa-engineer-mcp é compute-only e NÃO tem tool tokenless (_EXEMPT_TOOLS vazio):
o branch exempt é exercitado via monkeypatch de _EXEMPT_TOOLS.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from src.config.settings import Settings
from src.server import mcp_server as M

# Conjunto canônico das 19 tools declaradas no servidor.
_EXPECTED_TOOLS = {
    "analyze_quality_requirement",
    "classify_bug_severity",
    "validate_story_testability",
    "review_test_coverage",
    "generate_test_plan",
    "generate_test_cases",
    "generate_gherkin_scenarios",
    "generate_e2e_tests",
    "generate_api_tests",
    "generate_unit_tests",
    "generate_playwright_tests",
    "generate_cypress_tests",
    "generate_postman_collection",
    "generate_bug_report",
    "generate_quality_gate",
    "generate_uat_checklist",
    "generate_k6_performance_test",
    "generate_regression_suite",
    "generate_smoke_test_suite",
}

# Tools de leitura (:read) vs geradoras (:write).
_READ_TOOLS = {
    "analyze_quality_requirement",
    "classify_bug_severity",
    "validate_story_testability",
    "review_test_coverage",
}


def _settings() -> Settings:
    return Settings(
        MCP_TWIN_AUDIENCE="mcp:qa-engineer-mcp",
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
    assert body == {"status": "ok", "service": "qa-engineer-mcp", "tools": 19}


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
        # required_scope no formato dominio:tipo:acao
        assert t["required_scope"].count(":") == 2
        # capability é o id estável <namespace>.<tool>
        assert t["capability"] == f"qa-engineer-mcp.{t['name']}"
    # leitura/análise usam verbo :read; geradores usam :write.
    by_name = {t["name"]: t for t in tools}
    for name in _READ_TOOLS:
        assert by_name[name]["required_scope"].endswith(":read"), name
    for name in _EXPECTED_TOOLS - _READ_TOOLS:
        assert by_name[name]["required_scope"].endswith(":write"), name


# ── /mcp/tools/call — tool exempt (sem token) ─────────────────────────────────
def test_call_exempt_tool_without_token(client: TestClient, monkeypatch):
    # qa-engineer não declara tool tokenless; exercitamos o branch via denylist inversa.
    monkeypatch.setattr(M, "_EXEMPT_TOOLS", frozenset({"analyze_quality_requirement"}))
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "analyze_quality_requirement", "arguments": {"requirement": "R"}}},
    )
    assert r.status_code == 200
    text = r.json()["result"]["content"][0]["text"]
    payload = json.loads(text)
    assert payload["requirement"] == "R"
    assert payload["automation_feasibility"] == "high"


# ── /mcp/tools/call — sem inner token → 401 ───────────────────────────────────
def test_call_missing_twin_token(client: TestClient):
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "generate_test_cases", "arguments": {"feature": "X"}}},
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
                "name": "generate_test_cases",
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
                "name": "generate_test_cases",
                # tenant do cliente deve ser IGNORADO/sobrescrito pelas claims
                "arguments": {"feature": "X", "tenant_id": "ATTACKER"},
                "_meta": {"twin_token": "tok"},
            }
        },
    )
    assert r.status_code == 200
    assert captured["name"] == "generate_test_cases"
    assert captured["args"]["tenant_id"] == "T-42"  # das claims, não "ATTACKER"


# ── /mcp/tools/call — token sem tenant nas claims → 401 ───────────────────────
def test_call_valid_token_without_tenant(client: TestClient, monkeypatch):
    monkeypatch.setattr(M, "_verify_inner_token", lambda _t, _s: {"jti": "j"})
    r = client.post(
        "/mcp/tools/call",
        json={
            "params": {
                "name": "generate_test_cases",
                "arguments": {},
                "_meta": {"twin_token": "t"},
            }
        },
    )
    assert r.status_code == 401
    assert r.json()["error"] == "missing_tenant_scope"


# ── /mcp/tools/call — token válido despacha e serializa payload (happy path) ───
def test_call_valid_token_dispatches_real_tool(client: TestClient, monkeypatch):
    monkeypatch.setattr(M, "_verify_inner_token", lambda _t, _s: {"tenant_id": "T-9", "jti": "j"})
    r = client.post(
        "/mcp/tools/call",
        json={
            "params": {
                "name": "classify_bug_severity",
                "arguments": {"description": "crash", "impact": "critical", "frequency": "always"},
                "_meta": {"twin_token": "t"},
            }
        },
    )
    assert r.status_code == 200
    payload = json.loads(r.json()["result"]["content"][0]["text"])
    assert payload["severity"] == "P1"
    # tenant injetado nos args mas ignorado pela tool compute-only.
    assert payload["description"] == "crash"


# ── /mcp/tools/call — erro interno da tool vira payload de erro (200) ──────────
def test_call_internal_error_is_wrapped(client: TestClient, monkeypatch):
    monkeypatch.setattr(M, "_verify_inner_token", lambda _t, _s: {"tenant_id": "T", "jti": "j"})

    def _boom(_name, _args):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(M, "_dispatch", _boom)
    r = client.post(
        "/mcp/tools/call",
        json={
            "params": {
                "name": "generate_test_cases",
                "arguments": {"feature": "X"},
                "_meta": {"twin_token": "t"},
            }
        },
    )
    assert r.status_code == 200
    payload = json.loads(r.json()["result"]["content"][0]["text"])
    assert payload["error"] == "internal_error"
    assert payload["detail"] == "kaboom"
    assert payload["tool"] == "generate_test_cases"


# ── /mcp/tools/call — denylist (exclude) → 403 ────────────────────────────────
def test_call_excluded_tool(client: TestClient, monkeypatch):
    monkeypatch.setattr(M, "_EXCLUDE_TOOLS", frozenset({"generate_test_cases"}))
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "generate_test_cases", "arguments": {}}},
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


# ── _dispatch cobre as 19 tools + KeyError ────────────────────────────────────
def test_dispatch_routes_all_tools():
    assert "quality_dimensions" in M._dispatch("analyze_quality_requirement", {})
    assert "severity" in M._dispatch("classify_bug_severity", {})
    assert "testability_score" in M._dispatch("validate_story_testability", {})
    assert "target_coverage" in M._dispatch("review_test_coverage", {})
    assert "test_levels" in M._dispatch("generate_test_plan", {})
    assert "cases" in M._dispatch("generate_test_cases", {})
    assert "scenarios" in M._dispatch("generate_gherkin_scenarios", {})
    assert "code" in M._dispatch("generate_e2e_tests", {})
    assert "pytest_code" in M._dispatch("generate_api_tests", {})
    assert "code" in M._dispatch("generate_unit_tests", {})
    assert "code" in M._dispatch("generate_playwright_tests", {})
    assert "code" in M._dispatch("generate_cypress_tests", {})
    assert "item" in M._dispatch("generate_postman_collection", {})
    assert "steps_to_reproduce" in M._dispatch("generate_bug_report", {})
    assert "gates" in M._dispatch("generate_quality_gate", {})
    assert "checklist" in M._dispatch("generate_uat_checklist", {})
    assert "script" in M._dispatch("generate_k6_performance_test", {})
    assert "cases" in M._dispatch("generate_regression_suite", {})
    assert "tests" in M._dispatch("generate_smoke_test_suite", {})
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
    assert settings.mcp_twin_audience == "mcp:qa-engineer-mcp"
    assert http_app.title.startswith("qa-engineer-mcp")
