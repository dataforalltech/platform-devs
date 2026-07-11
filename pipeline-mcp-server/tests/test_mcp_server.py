"""Sidecar mcp_http + PEP inner-token (RS256 REAL) — §16 / Test Doubles Policy.

RS256 é real: chave gerada, token assinado, verificador real (o PyJWKClient serve a
chave pública local — sem bypass, sem HS*). O caminho de execução com estado (happy
path / dispatch / unknown) roda contra MySQL real via `_run_tool`/`_dispatch`.
"""

from __future__ import annotations

import jwt
import pytest
from fastapi.testclient import TestClient

from src.config.settings import PipelineSettings
from src.server import mcp_server as M

from .conftest import TENANT_A, _test_settings, mint_token, patch_jwks, requires_mysql

_EXPECTED_TOOLS = {
    "register_pipeline",
    "get_pipeline",
    "list_pipeline",
    "promote_service",
    "approve_promotion",
    "watch_prs",
    "block_service",
    "rollback",
    "add_gate_result",
    "get_gate_status",
    "clear_gates",
    "get_promotion_history",
    "get_pipeline_overview",
    "set_pipeline_config",
}


def _settings(**over) -> PipelineSettings:
    return PipelineSettings(
        MCP_TWIN_AUDIENCE="mcp:pipeline-mcp",
        URL_ADMIN_TWIN_JWKS="http://admin.local/jwks.json",
        github_token="",
        github_org="",
        **over,
    )


@pytest.fixture()
def client() -> TestClient:
    return TestClient(M._build_http_app(_settings()))


# ── Schemas / catálogo (sem DB) ───────────────────────────────────────────────
def test_tool_count():
    assert len(M._TOOL_SCHEMAS) == 14


def test_required_fields_are_subset_of_properties():
    for name, meta in M._TOOL_SCHEMAS.items():
        props = set(meta["schema"].get("properties", {}).keys())
        required = set(meta["schema"].get("required", []))
        assert required <= props, f"{name}: required fora de properties"


def test_health(client: TestClient):
    r = client.get("/v1/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "service": "pipeline-mcp", "tools": 14}


def test_tools_list_has_policy_fields(client: TestClient):
    tools = client.get("/mcp/tools/list").json()["result"]["tools"]
    assert {t["name"] for t in tools} == _EXPECTED_TOOLS
    for t in tools:
        assert t["inputSchema"]["type"] == "object"
        for field in ("capability", "required_scope", "resource_type", "data_domain"):
            assert t[field]
        assert t["required_scope"].count(":") == 2
        assert t["capability"] == f"pipeline-mcp.{t['name']}"


# ── /mcp/tools/call — PEP (RS256 real), caminhos que retornam antes do DB ──────
def test_call_missing_twin_token(client: TestClient):
    r = client.post(
        "/mcp/tools/call", json={"params": {"name": "get_pipeline", "arguments": {"service": "s"}}}
    )
    assert r.status_code == 401 and r.json()["error"] == "missing_twin_token"


def test_call_invalid_audience_rejected(client: TestClient, monkeypatch, rsa_key):
    patch_jwks(monkeypatch, rsa_key)
    tok = mint_token(rsa_key, aud="mcp:outro-servico")  # audiência errada → verificador real rejeita
    r = client.post(
        "/mcp/tools/call",
        json={
            "params": {"name": "get_pipeline", "arguments": {"service": "s"}, "_meta": {"twin_token": tok}}
        },
    )
    assert r.status_code == 401 and r.json()["error"] == "invalid_twin_token"


def test_call_token_without_jti_rejected(client: TestClient, monkeypatch, rsa_key):
    patch_jwks(monkeypatch, rsa_key)
    tok = mint_token(rsa_key, include_jti=False)  # sem jti → require falha
    r = client.post(
        "/mcp/tools/call",
        json={
            "params": {"name": "get_pipeline", "arguments": {"service": "s"}, "_meta": {"twin_token": tok}}
        },
    )
    assert r.status_code == 401 and r.json()["error"] == "invalid_twin_token"


def test_call_token_without_tenant(client: TestClient, monkeypatch, rsa_key):
    patch_jwks(monkeypatch, rsa_key)
    tok = mint_token(rsa_key, tenant_id=None)  # verifica OK mas sem tenant nas claims
    r = client.post(
        "/mcp/tools/call",
        json={
            "params": {"name": "get_pipeline", "arguments": {"service": "s"}, "_meta": {"twin_token": tok}}
        },
    )
    assert r.status_code == 401 and r.json()["error"] == "missing_tenant_scope"


def test_call_excluded_tool(client: TestClient, monkeypatch):
    monkeypatch.setattr(M, "_EXCLUDE_TOOLS", frozenset({"get_pipeline"}))
    r = client.post(
        "/mcp/tools/call", json={"params": {"name": "get_pipeline", "arguments": {"service": "s"}}}
    )
    assert r.status_code == 403 and r.json()["error"] == "tool_excluded"


# ── _verify_inner_token (RS256 real) ──────────────────────────────────────────
def test_verify_inner_token_unconfigured():
    s = PipelineSettings(MCP_TWIN_AUDIENCE="", URL_ADMIN_TWIN_JWKS="", github_token="", github_org="")
    with pytest.raises(PermissionError):
        M._verify_inner_token("tok", s)


def test_verify_inner_token_real_rs256(monkeypatch, rsa_key):
    patch_jwks(monkeypatch, rsa_key)
    claims = M._verify_inner_token(mint_token(rsa_key, tenant_id="T-9"), _settings())
    assert claims["tenant_id"] == "T-9"
    with pytest.raises(jwt.InvalidAudienceError):
        M._verify_inner_token(mint_token(rsa_key, aud="mcp:x"), _settings())


# ── stdio call_tool → recusa fail-closed (gateway-only) ───────────────────────
def test_build_server_stdio_and_smoke(monkeypatch):
    monkeypatch.setattr(M, "get_settings", lambda: _settings())
    server, settings, http_app = M.build_server()
    assert settings.mcp_twin_audience == "mcp:pipeline-mcp"
    assert http_app.title.startswith("pipeline-mcp")
    assert TestClient(http_app).get("/v1/health").json()["service"] == "pipeline-mcp"


# ── Execução com estado (MySQL real) ──────────────────────────────────────────
@pytest.mark.integration
@requires_mysql
async def test_dispatch_routes_all_tools(store_a):
    s = _settings()
    await store_a.register_pipeline("svc-a", "o/svc-a")

    async def d(name, args):
        return await M._dispatch(name, args, s, store_a)

    assert (await d("register_pipeline", {"service": "n", "repo": "o/n"}))["action"] == "created"
    assert (await d("get_pipeline", {"service": "svc-a"}))["service"] == "svc-a"
    assert (await d("list_pipeline", {}))["total"] >= 1
    assert (
        await d(
            "promote_service", {"service": "svc-a", "from_env": "dev", "to_env": "homol", "promoted_by": "u"}
        )
    )["can_promote"] is False
    assert (await d("approve_promotion", {"promotion_id": 999, "approved_by": "a"}))["error"] == "not_found"
    assert (await d("watch_prs", {}))["error"] == "github_not_configured"
    assert (await d("block_service", {"service": "svc-a", "reason": "r", "blocked_by": "a"}))["blocked"]
    await d("register_pipeline", {"service": "svc-r", "repo": "o/r"})
    assert (
        await d("rollback", {"service": "svc-r", "env": "prod", "to_version": "v1", "rolled_back_by": "ops"})
    )["rolled_back"] is True
    assert (
        await d(
            "add_gate_result", {"service": "svc-a", "env": "dev", "gate_type": "qa_tests", "passed": True}
        )
    )["gate_recorded"] is True
    assert "can_promote" in (await d("get_gate_status", {"service": "svc-a", "env": "homol"}))
    assert (await d("clear_gates", {"service": "svc-a", "env": "dev"}))["cleared"] is True
    assert (await d("get_promotion_history", {}))["limit"] == 20
    assert (await d("get_pipeline_overview", {}))["total_services"] >= 1
    assert (await d("set_pipeline_config", {"service": "svc-a", "gates_required": {"homol": ["qa_tests"]}}))[
        "updated"
    ] is True
    with pytest.raises(KeyError):
        await d("does_not_exist", {})


@pytest.mark.integration
@requires_mysql
async def test_run_tool_credential_zero_end_to_end(seed_platforms):
    """Caminho REAL: _run_tool -> _ensure_tenant_schema -> for_tenant (get_platform ->
    PLATFORMS) -> PipelineStore -> _dispatch, tudo em MySQL real."""
    M._SCHEMA_READY.discard(TENANT_A)
    settings = _test_settings()  # com ADMIN_DB_*/DB_* reais (resolve o tenant via PLATFORMS)
    result = await M._run_tool("register_pipeline", {"service": "e2e", "repo": "o/e2e"}, settings, TENANT_A)
    assert result["action"] == "created"
    got = await M._run_tool("get_pipeline", {"service": "e2e"}, settings, TENANT_A)
    assert got["service"] == "e2e"
    with pytest.raises(KeyError):
        await M._run_tool("nope", {}, settings, TENANT_A)
