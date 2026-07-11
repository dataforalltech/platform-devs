"""Sidecar mcp_http + PEP inner-token (RS256 REAL) — §16 / Test Doubles Policy.

RS256 é real: chave gerada, token assinado, verificador real (o PyJWKClient serve a
chave pública local — sem bypass, sem HS*). O caminho de execução com estado (dispatch
/ run_tool / unknown) roda contra MySQL real via `_run_tool`/`_dispatch`; os caminhos
de catálogo e PEP que retornam antes do DB são herméticos.
"""

from __future__ import annotations

import jwt
import pytest
from fastapi.testclient import TestClient

from src.config.settings import AuditSettings
from src.server import mcp_server as M

from .conftest import TENANT_A, _test_settings, mint_token, patch_jwks, requires_mysql

_EXPECTED_TOOLS = {
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


def _settings(**over) -> AuditSettings:
    return AuditSettings(
        MCP_TWIN_AUDIENCE="mcp:audit-mcp",
        URL_ADMIN_TWIN_JWKS="http://admin.local/jwks.json",
        **over,
    )


@pytest.fixture()
def client() -> TestClient:
    return TestClient(M._build_http_app(_settings()))


# ── Schemas / catálogo (sem DB) ───────────────────────────────────────────────
def test_tool_count():
    assert len(M._TOOL_SCHEMAS) == 9


def test_required_fields_are_subset_of_properties():
    for name, meta in M._TOOL_SCHEMAS.items():
        props = set(meta["schema"].get("properties", {}).keys())
        required = set(meta["schema"].get("required", []))
        assert required <= props, f"{name}: required fora de properties"


def test_health(client: TestClient):
    r = client.get("/v1/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "service": "audit-mcp", "tools": 9}


def test_tools_list_has_policy_fields(client: TestClient):
    tools = client.get("/mcp/tools/list").json()["result"]["tools"]
    assert {t["name"] for t in tools} == _EXPECTED_TOOLS
    for t in tools:
        assert t["inputSchema"]["type"] == "object"
        for field in ("capability", "required_scope", "resource_type", "data_domain"):
            assert t[field], f"{t['name']} sem {field}"
        assert t["required_scope"].count(":") == 2
        assert t["capability"] == f"audit-mcp.{t['name']}"
        assert t["required_scope"].startswith("audit-mcp:")
        assert t["data_domain"] == "compliance"
    by_name = {t["name"]: t for t in tools}
    # mutações usam verbo :write; consultas :read
    assert by_name["run_audit"]["required_scope"].endswith(":write")
    assert by_name["submit_audit_approval"]["required_scope"].endswith(":write")
    assert by_name["set_service_criticality"]["required_scope"].endswith(":write")
    assert by_name["get_compliance_policy"]["required_scope"].endswith(":read")
    assert by_name["list_audits"]["required_scope"].endswith(":read")


# ── /mcp/tools/call — PEP (RS256 real), caminhos que retornam antes do DB ──────
def test_call_missing_twin_token(client: TestClient):
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "get_compliance_policy", "arguments": {"env": "dev"}}},
    )
    assert r.status_code == 401 and r.json()["error"] == "missing_twin_token"


def test_call_invalid_audience_rejected(client: TestClient, monkeypatch, rsa_key):
    patch_jwks(monkeypatch, rsa_key)
    tok = mint_token(rsa_key, aud="mcp:outro-servico")  # audiência errada → verificador real rejeita
    r = client.post(
        "/mcp/tools/call",
        json={
            "params": {
                "name": "get_compliance_policy",
                "arguments": {"env": "dev"},
                "_meta": {"twin_token": tok},
            }
        },
    )
    assert r.status_code == 401 and r.json()["error"] == "invalid_twin_token"


def test_call_token_without_jti_rejected(client: TestClient, monkeypatch, rsa_key):
    patch_jwks(monkeypatch, rsa_key)
    tok = mint_token(rsa_key, include_jti=False)  # sem jti → require falha
    r = client.post(
        "/mcp/tools/call",
        json={
            "params": {
                "name": "get_compliance_policy",
                "arguments": {"env": "dev"},
                "_meta": {"twin_token": tok},
            }
        },
    )
    assert r.status_code == 401 and r.json()["error"] == "invalid_twin_token"


def test_call_token_without_tenant(client: TestClient, monkeypatch, rsa_key):
    patch_jwks(monkeypatch, rsa_key)
    tok = mint_token(rsa_key, tenant_id=None)  # verifica OK mas sem tenant nas claims
    r = client.post(
        "/mcp/tools/call",
        json={
            "params": {
                "name": "get_compliance_policy",
                "arguments": {"env": "dev"},
                "_meta": {"twin_token": tok},
            }
        },
    )
    assert r.status_code == 401 and r.json()["error"] == "missing_tenant_scope"


def test_call_excluded_tool(client: TestClient, monkeypatch):
    monkeypatch.setattr(M, "_EXCLUDE_TOOLS", frozenset({"get_compliance_policy"}))
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "get_compliance_policy", "arguments": {"env": "dev"}}},
    )
    assert r.status_code == 403 and r.json()["error"] == "tool_excluded"


# ── _verify_inner_token (RS256 real) ──────────────────────────────────────────
def test_verify_inner_token_unconfigured():
    s = AuditSettings(MCP_TWIN_AUDIENCE="", URL_ADMIN_TWIN_JWKS="")
    with pytest.raises(PermissionError):
        M._verify_inner_token("tok", s)


def test_verify_inner_token_real_rs256(monkeypatch, rsa_key):
    patch_jwks(monkeypatch, rsa_key)
    claims = M._verify_inner_token(mint_token(rsa_key, tenant_id="T-9"), _settings())
    assert claims["tenant_id"] == "T-9"
    with pytest.raises(jwt.InvalidAudienceError):
        M._verify_inner_token(mint_token(rsa_key, aud="mcp:x"), _settings())


# ── build_server: fábrica + sidecar (stdio gateway-only) ──────────────────────
def test_build_server_smoke(monkeypatch):
    monkeypatch.setattr(M, "get_settings", lambda: _settings())
    server, settings, http_app = M.build_server()
    assert server is not None
    assert settings.mcp_twin_audience == "mcp:audit-mcp"
    assert http_app.title.startswith("audit-mcp")
    assert TestClient(http_app).get("/v1/health").json()["service"] == "audit-mcp"


# ── Execução com estado (MySQL real) ──────────────────────────────────────────
@pytest.mark.integration
@requires_mysql
async def test_dispatch_routes_all_tools(store_a):
    s = _test_settings()

    async def d(name, args):
        return await M._dispatch(name, args, s, store_a)

    assert (await d("get_compliance_policy", {"env": "dev"}))["env"] == "dev"
    assert "checklist" in await d("get_compliance_checklist", {"service": "a", "repo": "r", "env": "dev"})
    assert (await d("get_audit_status", {"service": "s", "env": "dev"}))["status"] == "not_audited"
    assert (await d("list_audits", {}))["total"] == 0
    assert (await d("get_audit_report", {}))["total_audits"] == 0
    assert (await d("get_audit_gate_result", {"service": "s", "env": "dev"}))["passed"] is False
    crit = {"service": "s", "criticality": "high", "updated_by": "u"}
    assert (await d("set_service_criticality", crit))["success"] is True
    ra = await d("run_audit", {"service": "s", "repo": "ghost", "env": "dev"})
    assert ra["error"] == "ValidationError"
    appr = {"audit_id": "audit_x_dev", "approved_by": "a", "decision": "approved"}
    assert (await d("submit_audit_approval", appr))["error"] == "NotFound"
    with pytest.raises(KeyError):
        await d("does_not_exist", {})


@pytest.mark.integration
@requires_mysql
async def test_run_tool_credential_zero_end_to_end(seed_platforms):
    """Caminho REAL: _run_tool -> _ensure_tenant_schema -> for_tenant (get_platform ->
    PLATFORMS) -> AuditStore -> _dispatch, tudo em MySQL real."""
    M._SCHEMA_READY.discard(TENANT_A)
    settings = _test_settings()  # com ADMIN_DB_*/DB_* reais (resolve o tenant via PLATFORMS)
    ok = await M._run_tool(
        "set_service_criticality",
        {"service": "e2e", "criticality": "high", "updated_by": "u"},
        settings,
        TENANT_A,
    )
    assert ok["success"] is True
    got = await M._run_tool("get_audit_status", {"service": "e2e", "env": "dev"}, settings, TENANT_A)
    assert got["status"] == "not_audited"
    with pytest.raises(KeyError):
        await M._run_tool("nope", {}, settings, TENANT_A)
