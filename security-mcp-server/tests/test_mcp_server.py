"""Sidecar mcp_http + PEP inner-token (RS256 REAL) — §16 / Test Doubles Policy.

RS256 é real: chave gerada, token assinado, verificador real (o PyJWKClient serve a
chave pública local — sem bypass, sem HS*). O caminho de execução com estado (happy
path / dispatch / unknown) roda contra MySQL real via `_run_tool`/`_dispatch`.
"""

from __future__ import annotations

import jwt
import pytest
from fastapi.testclient import TestClient

from src.config.settings import SecuritySettings
from src.server import mcp_server as M

from .conftest import TENANT_A, _test_settings, mint_token, patch_jwks, requires_mysql

_EXPECTED_TOOLS = {
    "save_threat_model",
    "list_threat_models",
    "get_threat_model",
    "update_threat_model",
    "delete_threat_model",
    "set_security_control",
    "list_security_controls",
    "get_security_control",
    "delete_security_control",
    "save_cvss_assessment",
    "list_cvss_assessments",
    "get_cvss_assessment",
    "delete_cvss_assessment",
    "save_security_artifact",
    "list_security_artifacts",
    "get_security_artifact",
    "delete_security_artifact",
    "generate_security_controls",
    "generate_api_security_spec",
    "generate_compliance_report",
    "generate_security_handbook",
}


def _settings(**over) -> SecuritySettings:
    return SecuritySettings(
        MCP_TWIN_AUDIENCE="mcp:security-mcp",
        URL_ADMIN_TWIN_JWKS="http://admin.local/jwks.json",
        **over,
    )


@pytest.fixture()
def client() -> TestClient:
    return TestClient(M._build_http_app(_settings()))


# ── Schemas / catálogo (sem DB) ───────────────────────────────────────────────
def test_tool_count():
    assert len(M._TOOL_SCHEMAS) == 21
    assert set(M._TOOL_SCHEMAS) == _EXPECTED_TOOLS


def test_required_fields_are_subset_of_properties():
    for name, meta in M._TOOL_SCHEMAS.items():
        props = set(meta["schema"].get("properties", {}).keys())
        required = set(meta["schema"].get("required", []))
        assert required <= props, f"{name}: required fora de properties"


def test_health(client: TestClient):
    r = client.get("/v1/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "service": "security-mcp", "tools": 21}


def test_tools_list_has_policy_fields(client: TestClient):
    tools = client.get("/mcp/tools/list").json()["result"]["tools"]
    assert {t["name"] for t in tools} == _EXPECTED_TOOLS
    for t in tools:
        assert t["inputSchema"]["type"] == "object"
        for field in ("capability", "required_scope", "resource_type", "data_domain"):
            assert t[field]
        assert t["required_scope"].count(":") == 2
        assert t["capability"] == f"security-mcp.{t['name']}"


# ── /mcp/tools/call — PEP (RS256 real), caminhos que retornam antes do DB ──────
def test_call_missing_twin_token(client: TestClient):
    r = client.post("/mcp/tools/call", json={"params": {"name": "get_threat_model", "arguments": {"id": 1}}})
    assert r.status_code == 401 and r.json()["error"] == "missing_twin_token"


def test_call_invalid_audience_rejected(client: TestClient, monkeypatch, rsa_key):
    patch_jwks(monkeypatch, rsa_key)
    tok = mint_token(rsa_key, aud="mcp:outro-servico")  # audiência errada → verificador real rejeita
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "get_threat_model", "arguments": {"id": 1}, "_meta": {"twin_token": tok}}},
    )
    assert r.status_code == 401 and r.json()["error"] == "invalid_twin_token"


def test_call_token_without_jti_rejected(client: TestClient, monkeypatch, rsa_key):
    patch_jwks(monkeypatch, rsa_key)
    tok = mint_token(rsa_key, include_jti=False)  # sem jti → require falha
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "get_threat_model", "arguments": {"id": 1}, "_meta": {"twin_token": tok}}},
    )
    assert r.status_code == 401 and r.json()["error"] == "invalid_twin_token"


def test_call_token_expired_rejected(client: TestClient, monkeypatch, rsa_key):
    patch_jwks(monkeypatch, rsa_key)
    tok = mint_token(rsa_key, exp_delta=-10)  # já expirado → verificador real rejeita
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "get_threat_model", "arguments": {"id": 1}, "_meta": {"twin_token": tok}}},
    )
    assert r.status_code == 401 and r.json()["error"] == "invalid_twin_token"


def test_call_token_without_tenant(client: TestClient, monkeypatch, rsa_key):
    patch_jwks(monkeypatch, rsa_key)
    tok = mint_token(rsa_key, tenant_id=None)  # verifica OK mas sem tenant nas claims
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "get_threat_model", "arguments": {"id": 1}, "_meta": {"twin_token": tok}}},
    )
    assert r.status_code == 401 and r.json()["error"] == "missing_tenant_scope"


def test_call_excluded_tool(client: TestClient, monkeypatch):
    monkeypatch.setattr(M, "_EXCLUDE_TOOLS", frozenset({"get_threat_model"}))
    r = client.post("/mcp/tools/call", json={"params": {"name": "get_threat_model", "arguments": {"id": 1}}})
    assert r.status_code == 403 and r.json()["error"] == "tool_excluded"


# ── _verify_inner_token (RS256 real) ──────────────────────────────────────────
def test_verify_inner_token_unconfigured():
    s = SecuritySettings(MCP_TWIN_AUDIENCE="", URL_ADMIN_TWIN_JWKS="")
    with pytest.raises(PermissionError):
        M._verify_inner_token("tok", s)


def test_verify_inner_token_real_rs256(monkeypatch, rsa_key):
    patch_jwks(monkeypatch, rsa_key)
    claims = M._verify_inner_token(mint_token(rsa_key, tenant_id="T-9"), _settings())
    assert claims["tenant_id"] == "T-9"
    with pytest.raises(jwt.InvalidAudienceError):
        M._verify_inner_token(mint_token(rsa_key, aud="mcp:x"), _settings())


# ── stdio call_tool → smoke do build_server (gateway-only) ────────────────────
def test_build_server_stdio_and_smoke(monkeypatch):
    monkeypatch.setattr(M, "get_settings", lambda: _settings())
    server, settings, http_app = M.build_server()
    assert settings.mcp_twin_audience == "mcp:security-mcp"
    assert http_app.title.startswith("security-mcp")
    assert TestClient(http_app).get("/v1/health").json()["service"] == "security-mcp"


# ── Execução com estado (MySQL real) ──────────────────────────────────────────
@pytest.mark.integration
@requires_mysql
async def test_dispatch_routes_all_tools(store_a):
    async def d(name, args):
        return await M._dispatch(name, args, store_a)

    # Threat Models
    model = (await d("save_threat_model", {"system_name": "s", "threats": [{"id": "T01"}]}))["threat_model"]
    assert (await d("list_threat_models", {}))["total"] == 1
    assert (await d("get_threat_model", {"id": model["id"]}))["system_name"] == "s"
    assert (await d("update_threat_model", {"id": model["id"], "status": "ok"}))["updated"] is True
    assert (await d("delete_threat_model", {"id": model["id"]}))["deleted"] is True

    # Security Controls (upsert por (system_name, control_key))
    assert (await d("set_security_control", {"system_name": "s", "control_key": "auth"}))["saved"] is True
    assert (await d("list_security_controls", {}))["total"] == 1
    got = await d("get_security_control", {"system_name": "s", "control_key": "auth"})
    assert got["control_key"] == "auth"
    assert (await d("delete_security_control", {"system_name": "s", "control_key": "auth"}))[
        "deleted"
    ] is True

    # CVSS Assessments (score/severity calculados do vetor)
    saved = await d("save_cvss_assessment", {"vector": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"})
    cvss = saved["cvss_assessment"]
    assert cvss["base_score"] == 9.8 and cvss["severity"] == "Critical"
    assert (await d("list_cvss_assessments", {"severity": "Critical"}))["total"] == 1
    assert (await d("get_cvss_assessment", {"id": cvss["id"]}))["severity"] == "Critical"
    assert (await d("delete_cvss_assessment", {"id": cvss["id"]}))["deleted"] is True

    # Security Artifacts
    art = (await d("save_security_artifact", {"kind": "headers", "target": "edge", "content": "x"}))[
        "security_artifact"
    ]
    assert (await d("list_security_artifacts", {}))["total"] == 1
    assert (await d("get_security_artifact", {"id": art["id"]}))["kind"] == "headers"
    assert (await d("delete_security_artifact", {"id": art["id"]}))["deleted"] is True

    with pytest.raises(KeyError):
        await d("does_not_exist", {})


@pytest.mark.integration
@requires_mysql
async def test_dispatch_validation_paths(store_a):
    # kind inválido de artefato → erro sem persistir
    bad = await M._dispatch("save_security_artifact", {"kind": "nope", "target": "x"}, store_a)
    assert bad["error"] == "invalid_kind"
    # vetor CVSS incompleto → erro sem persistir
    bad_cvss = await M._dispatch("save_cvss_assessment", {"vector": "CVSS:3.1/AV:N"}, store_a)
    assert bad_cvss["error"] == "vetor_incompleto"
    # get de id inexistente → not_found
    missing = await M._dispatch("get_threat_model", {"id": 999999}, store_a)
    assert missing["error"] == "not_found"


@pytest.mark.integration
@requires_mysql
async def test_run_tool_credential_zero_end_to_end(seed_platforms):
    """Caminho REAL: _run_tool -> _ensure_tenant_schema -> for_tenant (get_platform ->
    PLATFORMS) -> SecurityStore -> _dispatch, tudo em MySQL real."""
    M._SCHEMA_READY.discard(TENANT_A)
    settings = _test_settings()  # com ADMIN_DB_*/DB_* reais (resolve o tenant via PLATFORMS)
    saved = await M._run_tool(
        "save_cvss_assessment",
        {"vector": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H", "label": "CVE-e2e"},
        settings,
        TENANT_A,
    )
    assert saved["saved"] is True and saved["cvss_assessment"]["severity"] == "Critical"
    listed = await M._run_tool("list_cvss_assessments", {}, settings, TENANT_A)
    assert listed["total"] == 1
    with pytest.raises(KeyError):
        await M._run_tool("nope", {}, settings, TENANT_A)
