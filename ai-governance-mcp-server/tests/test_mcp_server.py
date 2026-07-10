"""Testes do sidecar mcp_http + PEP inner-token (STD-MCP-001 / STD-SEC-006).

Cobre: /v1/health, /mcp/tools/list (campos de policy), /mcp/tools/call
(missing/invalid token, exempt, tenant das claims, exclude, unknown, internal),
_verify_inner_token (configurado/não), _dispatch (status, roteamento de TODAS as
tools via stubs, erros de domínio) e build_server smoke. O PyJWKClient/JWKS é
sempre mockado — os testes nunca fazem I/O de rede (FID-01 / Test Doubles Policy).
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from src.config.settings import Settings
from src.server import mcp_server as M
from src.tools import GraphUnavailable, SuggestionsUnavailable

# Nomes (no namespace do módulo M) de TODAS as funções puras roteadas por _route.
_TOOL_FUNCS = [
    "get_agent_guidelines",
    "get_layer_policy",
    "get_forbidden_actions",
    "validate_agent_decision",
    "get_fallback_policy",
    "get_contract_change_policy",
    "get_final_response_template",
    "get_pre_execution_checklist",
    "search_governance_knowledge",
    "query_ecosystem_graph",
    "find_consumers_of",
    "find_dependencies_of",
    "get_service_metadata",
    "submit_suggestion",
    "list_suggestions",
    "get_suggestion",
    "update_suggestion_status",
    "get_service_ownership",
    "get_service_dependencies",
    "get_port_map",
    "check_scope",
    "validate_lib_change",
    "validate_migration",
    "create_adr",
    "get_audit_log",
]

# Tools roteadas (todas menos a exempt 'status').
_ROUTED_TOOLS = [n for n in M._TOOL_SCHEMAS if n != "status"]


def _settings() -> Settings:
    return Settings(
        MCP_TWIN_AUDIENCE="mcp:ai-governance-mcp",
        URL_ADMIN_TWIN_JWKS="http://admin.local/.well-known/jwks.json",
    )


class _DummyAudit:
    def record(self, *a, **k) -> None:  # noqa: D401
        return None


@pytest.fixture()
def client() -> TestClient:
    return TestClient(M._build_http_app(_settings()))


@pytest.fixture()
def stub_tools(monkeypatch):
    """Stuba _get_repo/_get_audit e TODAS as funções de tool (sem tocar KB/FS)."""
    monkeypatch.setattr(M, "_get_repo", lambda: object())
    monkeypatch.setattr(M, "_get_audit", lambda: _DummyAudit())
    for fn in _TOOL_FUNCS:
        monkeypatch.setattr(M, fn, lambda *a, **k: {"ok": True, "input_summary": {}})
    return monkeypatch


# ── /v1/health ────────────────────────────────────────────────────────────────
def test_health(client: TestClient):
    r = client.get("/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body == {"status": "ok", "service": "ai-governance-mcp", "tools": len(M._TOOL_SCHEMAS)}


# ── /mcp/tools/list — todos os 4 campos de policy (CI-2) ──────────────────────
def test_tools_list_has_policy_fields(client: TestClient):
    r = client.get("/mcp/tools/list")
    assert r.status_code == 200
    tools = r.json()["result"]["tools"]
    assert {t["name"] for t in tools} == set(M._TOOL_SCHEMAS.keys())
    for t in tools:
        assert t["inputSchema"]["type"] == "object"
        for field in ("capability", "required_scope", "resource_type", "data_domain"):
            assert t[field], f"{t['name']} sem {field}"
        # required_scope no formato dominio:tipo:acao (3 segmentos)
        assert t["required_scope"].count(":") == 2
        assert t["required_scope"].startswith("ai-governance-mcp:")
        assert t["capability"] == f"ai-governance-mcp.{t['name']}"
    by_name = {t["name"]: t for t in tools}
    # writes usam :write; leituras usam :read
    assert by_name["status"]["required_scope"].endswith(":read")
    assert by_name["submit_suggestion"]["required_scope"].endswith(":write")
    assert by_name["update_suggestion_status"]["required_scope"].endswith(":write")
    assert by_name["create_adr"]["required_scope"].endswith(":write")
    assert by_name["get_layer_policy"]["required_scope"].endswith(":read")


# ── /mcp/tools/call — tool exempt (sem token) ─────────────────────────────────
def test_call_exempt_status_without_token(client: TestClient):
    r = client.post("/mcp/tools/call", json={"params": {"name": "status", "arguments": {}}})
    assert r.status_code == 200
    text = r.json()["result"]["content"][0]["text"]
    payload = json.loads(text)
    assert payload["status"] == "ok"
    assert payload["service"] == "ai-governance-mcp"


# ── /mcp/tools/call — sem inner token → 401 ───────────────────────────────────
def test_call_missing_twin_token(client: TestClient):
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "get_port_map", "arguments": {}}},
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
                "name": "get_port_map",
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

    def _spy(name, args):
        captured["name"] = name
        captured["args"] = dict(args)
        return {"ok": True}

    monkeypatch.setattr(M, "_dispatch", _spy)
    r = client.post(
        "/mcp/tools/call",
        json={
            "params": {
                "name": "get_port_map",
                # tenant do cliente deve ser IGNORADO/sobrescrito pelas claims
                "arguments": {"tenant_id": "ATTACKER"},
                "_meta": {"twin_token": "tok"},
            }
        },
    )
    assert r.status_code == 200
    assert captured["name"] == "get_port_map"
    assert captured["args"]["tenant_id"] == "T-42"  # das claims, não "ATTACKER"


# ── /mcp/tools/call — token sem tenant nas claims → 401 ───────────────────────
def test_call_valid_token_without_tenant(client: TestClient, monkeypatch):
    monkeypatch.setattr(M, "_verify_inner_token", lambda _t, _s: {"jti": "j"})
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "get_port_map", "arguments": {}, "_meta": {"twin_token": "t"}}},
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


# ── /mcp/tools/call — erro interno inesperado → payload internal_error ─────────
def test_call_internal_error(client: TestClient, monkeypatch):
    monkeypatch.setattr(M, "_verify_inner_token", lambda _t, _s: {"tenant_id": "T"})

    def _boom(_name, _args):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(M, "_dispatch", _boom)
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "get_port_map", "arguments": {}, "_meta": {"twin_token": "t"}}},
    )
    assert r.status_code == 200
    payload = json.loads(r.json()["result"]["content"][0]["text"])
    assert payload["error"] == "internal_error"
    assert payload["tool"] == "get_port_map"


# ── _dispatch — status não precisa de repo ────────────────────────────────────
def test_dispatch_status_is_repo_free():
    out = M._dispatch("status", {})
    assert out["status"] == "ok"
    assert out["service"] == "ai-governance-mcp"
    assert out["tools"] == len(M._TOOL_SCHEMAS)


# ── _dispatch — roteia TODAS as tools (via stubs; cobre cada branch de _route) ─
@pytest.mark.parametrize("name", _ROUTED_TOOLS)
def test_dispatch_routes_every_tool(name, stub_tools):
    out = M._dispatch(name, {})
    assert isinstance(out, dict)
    assert out.get("ok") is True


# ── _dispatch — tool desconhecida propaga KeyError ────────────────────────────
def test_dispatch_unknown_raises_keyerror(stub_tools):
    with pytest.raises(KeyError):
        M._dispatch("does_not_exist", {})


# ── _dispatch — erros de domínio viram payload de erro claro ──────────────────
def test_dispatch_graph_unavailable(stub_tools):
    stub_tools.setattr(M, "get_port_map", lambda *a, **k: (_ for _ in ()).throw(GraphUnavailable()))
    out = M._dispatch("get_port_map", {})
    assert out["error"] == "ecosystem_graph_unavailable"
    assert out["tool"] == "get_port_map"


def test_dispatch_suggestions_unavailable(stub_tools):
    stub_tools.setattr(M, "list_suggestions", lambda *a, **k: (_ for _ in ()).throw(SuggestionsUnavailable()))
    out = M._dispatch("list_suggestions", {})
    assert out["error"] == "suggestions_store_unavailable"


def test_dispatch_validation_error(stub_tools):
    stub_tools.setattr(M, "get_layer_policy", lambda *a, **k: (_ for _ in ()).throw(ValueError("bad layer")))
    out = M._dispatch("get_layer_policy", {})
    assert out["error"] == "validation_error"
    assert "bad layer" in out["details"]


# ── validate_agent_decision — grava na trilha de auditoria (best-effort) ──────
def test_dispatch_validate_agent_decision_records_audit(monkeypatch):
    monkeypatch.setattr(M, "_get_repo", lambda: object())
    recorded: dict = {}

    class _Audit:
        def record(self, result, summary=None):
            recorded["result"] = result
            recorded["summary"] = summary

    monkeypatch.setattr(M, "_get_audit", lambda: _Audit())
    monkeypatch.setattr(
        M, "validate_agent_decision", lambda *a, **k: {"approved": True, "input_summary": {"x": 1}}
    )
    out = M._dispatch("validate_agent_decision", {"repository_name": "r"})
    assert out["approved"] is True
    assert recorded["result"] == out
    assert recorded["summary"] == {"x": 1}


def test_dispatch_audit_write_failure_is_swallowed(monkeypatch):
    monkeypatch.setattr(M, "_get_repo", lambda: object())

    class _Audit:
        def record(self, *a, **k):
            raise OSError("disk full")

    monkeypatch.setattr(M, "_get_audit", lambda: _Audit())
    monkeypatch.setattr(M, "validate_agent_decision", lambda *a, **k: {"approved": False})
    # não deve levantar — a falha de auditoria é logada, não propagada
    out = M._dispatch("validate_agent_decision", {"repository_name": "r"})
    assert out["approved"] is False


# ── _verify_inner_token não configurado → PermissionError (fail-closed) ────────
def test_verify_inner_token_unconfigured():
    s = Settings(MCP_TWIN_AUDIENCE="", URL_ADMIN_TWIN_JWKS="")
    with pytest.raises(PermissionError):
        M._verify_inner_token("tok", s)


# ── _verify_inner_token happy path (JWKS + decode mockados) ───────────────────
def test_verify_inner_token_decodes_with_mocked_jwks(monkeypatch):
    class _Key:
        key = "signing-key"

    class _JWKClient:
        def __init__(self, _url):
            pass

        def get_signing_key_from_jwt(self, _tok):
            return _Key()

    captured: dict = {}

    def _decode(token, key, algorithms, audience, options):
        captured.update(token=token, key=key, algorithms=algorithms, audience=audience, options=options)
        return {"tenant_id": "T-1", "jti": "j", "aud": audience}

    monkeypatch.setattr(M.jwt, "PyJWKClient", _JWKClient)
    monkeypatch.setattr(M.jwt, "decode", _decode)

    claims = M._verify_inner_token("tok", _settings())
    assert claims["tenant_id"] == "T-1"
    assert captured["algorithms"] == ["RS256"]
    assert captured["audience"] == "mcp:ai-governance-mcp"
    assert set(captured["options"]["require"]) == {"exp", "aud", "jti"}


# ── _get_repo / _get_audit — singletons lazy (isolado de KB/FS) ───────────────
def test_get_repo_and_audit_are_cached_singletons(monkeypatch):
    # Reseta os singletons do módulo p/ um estado limpo.
    monkeypatch.setattr(M, "_repo", None)
    monkeypatch.setattr(M, "_audit", None)

    class _S:
        kb_path = "kb"
        effective_suggestions_path = "sugg"
        effective_audit_path = "audit"

    calls = {"repo": 0, "audit": 0}

    class _Repo:
        def __init__(self, **k):
            calls["repo"] += 1

    class _Audit:
        def __init__(self, **k):
            calls["audit"] += 1

    monkeypatch.setattr(M, "get_settings", lambda: _S())
    monkeypatch.setattr(M, "GovernanceRepository", _Repo)
    monkeypatch.setattr(M, "AuditStore", _Audit)

    r1 = M._get_repo()
    r2 = M._get_repo()
    a1 = M._get_audit()
    a2 = M._get_audit()
    assert r1 is r2
    assert a1 is a2
    # construído uma única vez (singleton lazy)
    assert calls == {"repo": 1, "audit": 1}


# ── build_server smoke (cobre a fábrica + stdio Server + sidecar) ─────────────
def test_build_server_smoke(monkeypatch):
    monkeypatch.delenv("MCP_TWIN_AUDIENCE", raising=False)
    from src.config import settings as settings_mod

    settings_mod.get_settings.cache_clear()
    server, settings, http_app = M.build_server()
    assert server is not None
    assert settings.mcp_twin_audience == "mcp:ai-governance-mcp"
    assert http_app.title.startswith("ai-governance-mcp")
    settings_mod.get_settings.cache_clear()
