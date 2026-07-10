"""Testes do sidecar mcp_http + PEP inner-token (STD-MCP-001 / STD-SEC-006).

Cobre: /v1/health, /mcp/tools/list (campos de policy), /mcp/tools/call
(missing/invalid token, exempt, tenant das claims, exclude, unknown, happy path)
e _verify_inner_token não configurado. O PyJWKClient/JWKS é sempre mockado e o
PostgreSQL é substituído pelo ``FakeAuditStore`` — os testes nunca fazem I/O de
rede/DB (FID-01 / Test Doubles Policy).
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from src.config.settings import AuditSettings
from src.server import mcp_server as M

from .conftest import FakeAuditStore


def _settings() -> AuditSettings:
    return AuditSettings(
        MCP_TWIN_AUDIENCE="mcp:audit-mcp",
        URL_ADMIN_TWIN_JWKS="http://admin.local/.well-known/jwks.json",
        policies_path=str(__import__("pathlib").Path(__file__).parent.parent / "src" / "policies"),
    )


@pytest.fixture()
def store() -> FakeAuditStore:
    return FakeAuditStore(settings=_settings())


@pytest.fixture()
def client(store: FakeAuditStore) -> TestClient:
    return TestClient(M._build_http_app(_settings(), store))


# ── /v1/health ────────────────────────────────────────────────────────────────
def test_health(client: TestClient):
    r = client.get("/v1/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "service": "audit-mcp", "tools": 9}


# ── /mcp/tools/list — todos os 4 campos de policy (CI-2) ──────────────────────
def test_tools_list_has_policy_fields(client: TestClient):
    r = client.get("/mcp/tools/list")
    assert r.status_code == 200
    tools = r.json()["result"]["tools"]
    assert {t["name"] for t in tools} == {
        "run_audit",
        "get_audit_status",
        "get_compliance_policy",
        "get_compliance_checklist",
        "submit_audit_approval",
        "get_audit_report",
        "list_audits",
        "set_service_criticality",
        "get_audit_gate_result",
    }
    for t in tools:
        assert t["inputSchema"]["type"] == "object"
        for field in ("capability", "required_scope", "resource_type", "data_domain"):
            assert t[field], f"{t['name']} sem {field}"
        # required_scope no formato dominio:tipo:acao (3 segmentos)
        assert t["required_scope"].count(":") == 2
        assert t["capability"] == f"audit-mcp.{t['name']}"
        assert t["required_scope"].startswith("audit-mcp:")
    by_name = {t["name"]: t for t in tools}
    # mutações usam verbo :write; consultas :read
    assert by_name["run_audit"]["required_scope"].endswith(":write")
    assert by_name["submit_audit_approval"]["required_scope"].endswith(":write")
    assert by_name["set_service_criticality"]["required_scope"].endswith(":write")
    assert by_name["get_compliance_policy"]["required_scope"].endswith(":read")
    assert by_name["list_audits"]["required_scope"].endswith(":read")


# ── /mcp/tools/call — sem inner token → 401 ───────────────────────────────────
def test_call_missing_twin_token(client: TestClient):
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "run_audit", "arguments": {"service": "s", "repo": "r", "env": "dev"}}},
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
                "name": "get_compliance_policy",
                "arguments": {"env": "dev"},
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

    def _spy(name, args, _store, _settings):
        captured["name"] = name
        captured["args"] = dict(args)
        return {"ok": True}

    monkeypatch.setattr(M, "_dispatch", _spy)
    r = client.post(
        "/mcp/tools/call",
        json={
            "params": {
                "name": "get_compliance_policy",
                # tenant do cliente deve ser IGNORADO/sobrescrito pelas claims
                "arguments": {"env": "dev", "tenant_id": "ATTACKER"},
                "_meta": {"twin_token": "tok"},
            }
        },
    )
    assert r.status_code == 200
    assert captured["name"] == "get_compliance_policy"
    assert captured["args"]["tenant_id"] == "T-42"  # das claims, não "ATTACKER"


# ── /mcp/tools/call — token sem tenant nas claims → 401 ───────────────────────
def test_call_valid_token_without_tenant(client: TestClient, monkeypatch):
    monkeypatch.setattr(M, "_verify_inner_token", lambda _t, _s: {"jti": "j"})
    r = client.post(
        "/mcp/tools/call",
        json={
            "params": {
                "name": "get_compliance_policy",
                "arguments": {"env": "dev"},
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
                "name": "get_compliance_policy",
                "arguments": {"env": "dev"},
                "_meta": {"twin_token": "tok"},
            }
        },
    )
    assert r.status_code == 200
    payload = json.loads(r.json()["result"]["content"][0]["text"])
    # tenant_id injetado foi removido pelo dispatcher → a tool executou com sucesso
    assert payload["env"] == "dev"
    assert payload["min_score"] == 0.5


# ── /mcp/tools/call — tool exempt (sem token) via monkeypatch ─────────────────
def test_call_exempt_tool_without_token(client: TestClient, monkeypatch):
    monkeypatch.setattr(M, "_EXEMPT_TOOLS", frozenset({"get_compliance_policy"}))
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "get_compliance_policy", "arguments": {"env": "dev"}}},
    )
    assert r.status_code == 200
    payload = json.loads(r.json()["result"]["content"][0]["text"])
    assert payload["env"] == "dev"


# ── /mcp/tools/call — denylist (exclude) → 403 ────────────────────────────────
def test_call_excluded_tool(client: TestClient, monkeypatch):
    monkeypatch.setattr(M, "_EXCLUDE_TOOLS", frozenset({"get_compliance_policy"}))
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "get_compliance_policy", "arguments": {"env": "dev"}}},
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

    def _boom(name, args, _store, _settings):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(M, "_dispatch", _boom)
    r = client.post(
        "/mcp/tools/call",
        json={
            "params": {
                "name": "get_compliance_policy",
                "arguments": {"env": "dev"},
                "_meta": {"twin_token": "t"},
            }
        },
    )
    assert r.status_code == 200
    payload = json.loads(r.json()["result"]["content"][0]["text"])
    assert payload["error"] == "internal_error"
    assert "kaboom" in payload["detail"]


# ── _dispatch cobre as 9 tools + KeyError + strip de tenant + TypeError ────────
def test_dispatch_routes_all_tools(store: FakeAuditStore):
    s = _settings()

    def d(name, args):
        return M._dispatch(name, args, store, s)

    assert d("get_compliance_policy", {"env": "dev"})["env"] == "dev"
    assert "checklist" in d("get_compliance_checklist", {"service": "a", "repo": "r", "env": "dev"})
    assert d("get_audit_status", {"service": "s", "env": "dev"})["status"] == "not_audited"
    assert d("list_audits", {})["total"] == 0
    assert d("get_audit_report", {})["total_audits"] == 0
    assert d("get_audit_gate_result", {"service": "s", "env": "dev"})["passed"] is False
    crit_args = {"service": "s", "criticality": "high", "updated_by": "u"}
    assert d("set_service_criticality", crit_args)["success"] is True
    assert d("run_audit", {"service": "s", "repo": "ghost", "env": "dev"})["error"] == "ValidationError"
    appr_args = {"audit_id": "x", "approved_by": "a", "decision": "approved"}
    assert d("submit_audit_approval", appr_args)["error"] == "NotFound"
    with pytest.raises(KeyError):
        d("unknown", {})


def test_dispatch_strips_tenant_id(store: FakeAuditStore):
    """tenant_id injetado pelo PEP é removido antes de chamar a tool (INV-3)."""
    s = _settings()
    result = M._dispatch("get_compliance_policy", {"env": "dev", "tenant_id": "T"}, store, s)
    assert result["env"] == "dev"  # não vira invalid_arguments


def test_dispatch_invalid_arguments(store: FakeAuditStore):
    """Args extras/errados viram invalid_arguments (TypeError capturado)."""
    s = _settings()
    result = M._dispatch("get_compliance_policy", {"env": "dev", "bogus": 1}, store, s)
    assert result["error"] == "invalid_arguments"


# ── _verify_inner_token não configurado → PermissionError (fail-closed) ────────
def test_verify_inner_token_unconfigured():
    s = AuditSettings(MCP_TWIN_AUDIENCE="", URL_ADMIN_TWIN_JWKS="")
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
    assert captured["audience"] == "mcp:audit-mcp"
    assert set(captured["options"]["require"]) == {"exp", "aud", "jti"}


# ── build_server smoke (cobre a fábrica + stdio Server; store faked) ──────────
def test_build_server_smoke(monkeypatch):
    monkeypatch.setattr(M, "AuditStore", FakeAuditStore)
    from src.config import settings as settings_mod

    settings_mod.get_settings.cache_clear()
    server, settings, store, http_app = M.build_server()
    assert server is not None
    assert isinstance(store, FakeAuditStore)
    assert settings.mcp_twin_audience == "mcp:audit-mcp"
    assert http_app.title.startswith("audit-mcp")
    # health continua acessível no http_app retornado
    resp = TestClient(http_app).get("/v1/health")
    assert resp.json()["service"] == "audit-mcp"
    settings_mod.get_settings.cache_clear()
