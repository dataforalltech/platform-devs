"""Testes do sidecar mcp_http + PEP inner-token (STD-MCP-001 / STD-SEC-006).

Cobre: /v1/health, /mcp/tools/list (campos de policy), /mcp/tools/call
(missing/invalid token, exempt, tenant das claims, exclude, unknown), _dispatch
e _verify_inner_token não configurado. O PyJWKClient/JWKS é sempre mockado — os
testes nunca fazem I/O de rede (FID-01 / Test Doubles Policy).
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from src.config.settings import Settings
from src.server import mcp_server as M

# Total de tools registradas no catálogo do product-owner-mcp.
_TOOL_COUNT = 17


def _settings() -> Settings:
    return Settings(
        MCP_TWIN_AUDIENCE="mcp:product-owner-mcp",
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
    assert body == {"status": "ok", "service": "product-owner-mcp", "tools": _TOOL_COUNT}


# ── /mcp/tools/list — todos os 4 campos de policy (CI-2) ──────────────────────
def test_tools_list_has_policy_fields(client: TestClient):
    r = client.get("/mcp/tools/list")
    assert r.status_code == 200
    tools = r.json()["result"]["tools"]
    assert len(tools) == _TOOL_COUNT
    assert {t["name"] for t in tools} == {
        "analyze_product_problem",
        "calculate_rice_score",
        "prioritize_backlog",
        "map_product_risks",
        "map_user_journey",
        "map_user_personas",
        "generate_discovery_questions",
        "define_mvp_scope",
        "define_product_metrics",
        "define_product_vision",
        "generate_feature_spec",
        "generate_go_to_market_brief",
        "generate_handoff_to_architecture",
        "generate_handoff_to_design",
        "generate_handoff_to_engineering",
        "generate_release_plan",
        "generate_user_stories",
    }
    for t in tools:
        assert t["inputSchema"]["type"] == "object"
        for field in ("capability", "required_scope", "resource_type", "data_domain"):
            assert t[field], f"{t['name']} sem {field}"
        # capability = <namespace>.<tool>
        assert t["capability"] == f"product-owner-mcp.{t['name']}"
        # required_scope no formato dominio:tipo:acao
        assert t["required_scope"].count(":") == 2
    # geradores usam verbo :write; análise/cálculo são :read.
    by_name = {t["name"]: t for t in tools}
    assert by_name["generate_user_stories"]["required_scope"].endswith(":write")
    assert by_name["calculate_rice_score"]["required_scope"].endswith(":read")


# ── /mcp/tools/call — tool exempt (sem token) ─────────────────────────────────
def test_call_exempt_tool_without_token(client: TestClient, monkeypatch):
    # product-owner não tem tool exempt por padrão; simula uma p/ cobrir o ramo.
    monkeypatch.setattr(M, "_EXEMPT_TOOLS", frozenset({"analyze_product_problem"}))
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "analyze_product_problem", "arguments": {"problem_statement": "X"}}},
    )
    assert r.status_code == 200
    text = r.json()["result"]["content"][0]["text"]
    assert json.loads(text)["problem_statement"] == "X"


# ── /mcp/tools/call — sem inner token → 401 ───────────────────────────────────
def test_call_missing_twin_token(client: TestClient):
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "generate_user_stories", "arguments": {"feature": "F"}}},
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
                "name": "generate_user_stories",
                "arguments": {"feature": "F"},
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
                "name": "generate_user_stories",
                # tenant do cliente deve ser IGNORADO/sobrescrito pelas claims
                "arguments": {"feature": "F", "tenant_id": "ATTACKER"},
                "_meta": {"twin_token": "tok"},
            }
        },
    )
    assert r.status_code == 200
    assert captured["name"] == "generate_user_stories"
    assert captured["args"]["tenant_id"] == "T-42"  # das claims, não "ATTACKER"


# ── /mcp/tools/call — token sem tenant nas claims → 401 ───────────────────────
def test_call_valid_token_without_tenant(client: TestClient, monkeypatch):
    monkeypatch.setattr(M, "_verify_inner_token", lambda _t, _s: {"jti": "j"})
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "generate_user_stories", "arguments": {}, "_meta": {"twin_token": "t"}}},
    )
    assert r.status_code == 401
    assert r.json()["error"] == "missing_tenant_scope"


# ── /mcp/tools/call — denylist (exclude) → 403 ────────────────────────────────
def test_call_excluded_tool(client: TestClient, monkeypatch):
    monkeypatch.setattr(M, "_EXCLUDE_TOOLS", frozenset({"calculate_rice_score"}))
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "calculate_rice_score", "arguments": {}}},
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


# ── /mcp/tools/call — erro interno da tool vira payload de erro (200) ──────────
def test_call_internal_error_is_wrapped(client: TestClient, monkeypatch):
    monkeypatch.setattr(M, "_verify_inner_token", lambda _t, _s: {"tenant_id": "T"})

    def _boom(_name, _args):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(M, "_dispatch", _boom)
    r = client.post(
        "/mcp/tools/call",
        json={
            "params": {
                "name": "generate_user_stories",
                "arguments": {"feature": "F"},
                "_meta": {"twin_token": "t"},
            }
        },
    )
    assert r.status_code == 200
    payload = json.loads(r.json()["result"]["content"][0]["text"])
    assert payload["error"] == "internal_error"
    assert "kaboom" in payload["detail"]


# ── _dispatch cobre as 17 tools + KeyError ────────────────────────────────────
def test_dispatch_routes_all_tools():
    assert "root_cause_hypotheses" in M._dispatch("analyze_product_problem", {"problem_statement": "X"})
    assert (
        M._dispatch("calculate_rice_score", {"reach": 10, "impact": 1, "confidence": 1, "effort": 1})["score"]
        == 10.0
    )
    assert "prioritized_items" in M._dispatch("prioritize_backlog", {"items": [{"name": "A", "score": 5}]})
    assert "total_risks" in M._dispatch("map_product_risks", {"feature": "F", "risks": []})
    assert "stages" in M._dispatch("map_user_journey", {"persona": "Ana", "steps": ["a"]})
    assert M._dispatch("map_user_personas", {"personas": ["P"]})["count"] == 1
    assert "research_questions" in M._dispatch("generate_discovery_questions", {"hypothesis": "H"})
    assert "mvp_scope" in M._dispatch("define_mvp_scope", {"product": "P", "features": ["a"]})
    assert "kpis" in M._dispatch("define_product_metrics", {"product": "P", "objectives": ["o"]})
    assert "vision" in M._dispatch(
        "define_product_vision", {"product": "P", "target_audience": "a", "problem": "b"}
    )
    assert M._dispatch("generate_feature_spec", {"feature": "F"})["feature"] == "F"
    assert "key_messages" in M._dispatch(
        "generate_go_to_market_brief",
        {"product": "P", "target_segment": "s", "value_proposition": "v"},
    )
    assert "tech_requirements" in M._dispatch("generate_handoff_to_architecture", {"feature": "F"})
    assert "wireframes_brief" in M._dispatch("generate_handoff_to_design", {"feature": "F"})
    assert "definition_of_ready" in M._dispatch("generate_handoff_to_engineering", {"feature": "F"})
    assert "phases" in M._dispatch("generate_release_plan", {"product": "P", "features": ["f"]})
    assert M._dispatch("generate_user_stories", {"feature": "F"})["count"] >= 1
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
    assert settings.mcp_twin_audience == "mcp:product-owner-mcp"
    assert http_app.title.startswith("product-owner-mcp")
