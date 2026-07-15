"""Sidecar mcp_http + PEP inner-token (RS256 REAL) — §16 / Test Doubles Policy.

RS256 é real: chave gerada, token assinado, verificador real (o PyJWKClient serve a
chave pública local — sem bypass, sem HS*). O caminho de execução com estado (happy
path / dispatch / unknown) roda contra MySQL real via `_run_tool`/`_dispatch`.
"""

from __future__ import annotations

import jwt
import pytest
from fastapi.testclient import TestClient

from src.config.settings import ProductManagerSettings
from src.server import mcp_server as M

from .conftest import TENANT_A, _test_settings, mint_token, patch_jwks, requires_mysql

_EXPECTED_TOOLS = {
    "save_feature_spec",
    "list_feature_specs",
    "get_feature_spec",
    "update_feature_spec",
    "delete_feature_spec",
    "save_gtm_brief",
    "list_gtm_briefs",
    "get_gtm_brief",
    "update_gtm_brief",
    "delete_gtm_brief",
    "save_release_plan",
    "list_release_plans",
    "get_release_plan",
    "update_release_plan",
    "delete_release_plan",
    "set_product_vision",
    "list_product_visions",
    "get_product_vision",
    "delete_product_vision",
    "save_artifact",
    "list_artifacts",
    "get_artifact",
    "delete_artifact",
}


def _settings(**over) -> ProductManagerSettings:
    return ProductManagerSettings(
        MCP_TWIN_AUDIENCE="mcp:product-manager-mcp",
        URL_ADMIN_TWIN_JWKS="http://admin.local/jwks.json",
        **over,
    )


@pytest.fixture()
def client() -> TestClient:
    return TestClient(M._build_http_app(_settings()))


# ── Schemas / catálogo (sem DB) ───────────────────────────────────────────────
def test_tool_count():
    assert len(M._TOOL_SCHEMAS) == 23
    assert set(M._TOOL_SCHEMAS) == _EXPECTED_TOOLS


def test_required_fields_are_subset_of_properties():
    for name, meta in M._TOOL_SCHEMAS.items():
        props = set(meta["schema"].get("properties", {}).keys())
        required = set(meta["schema"].get("required", []))
        assert required <= props, f"{name}: required fora de properties"


def test_health(client: TestClient):
    r = client.get("/v1/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "service": "product-manager-mcp", "tools": 23}


def test_tools_list_has_policy_fields(client: TestClient):
    tools = client.get("/mcp/tools/list").json()["result"]["tools"]
    assert {t["name"] for t in tools} == _EXPECTED_TOOLS
    for t in tools:
        assert t["inputSchema"]["type"] == "object"
        for field in ("capability", "required_scope", "resource_type", "data_domain"):
            assert t[field]
        assert t["required_scope"].count(":") == 2
        assert t["capability"] == f"product-manager-mcp.{t['name']}"


# ── /mcp/tools/call — PEP (RS256 real), caminhos que retornam antes do DB ──────
def test_call_missing_twin_token(client: TestClient):
    r = client.post("/mcp/tools/call", json={"params": {"name": "get_feature_spec", "arguments": {"id": 1}}})
    assert r.status_code == 401 and r.json()["error"] == "missing_twin_token"


def test_call_invalid_audience_rejected(client: TestClient, monkeypatch, rsa_key):
    patch_jwks(monkeypatch, rsa_key)
    tok = mint_token(rsa_key, aud="mcp:outro-servico")  # audiência errada → verificador real rejeita
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "get_feature_spec", "arguments": {"id": 1}, "_meta": {"twin_token": tok}}},
    )
    assert r.status_code == 401 and r.json()["error"] == "invalid_twin_token"


def test_call_token_without_jti_rejected(client: TestClient, monkeypatch, rsa_key):
    patch_jwks(monkeypatch, rsa_key)
    tok = mint_token(rsa_key, include_jti=False)  # sem jti → require falha
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "get_feature_spec", "arguments": {"id": 1}, "_meta": {"twin_token": tok}}},
    )
    assert r.status_code == 401 and r.json()["error"] == "invalid_twin_token"


def test_call_token_expired_rejected(client: TestClient, monkeypatch, rsa_key):
    patch_jwks(monkeypatch, rsa_key)
    tok = mint_token(rsa_key, exp_delta=-10)  # já expirado → verificador real rejeita
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "get_feature_spec", "arguments": {"id": 1}, "_meta": {"twin_token": tok}}},
    )
    assert r.status_code == 401 and r.json()["error"] == "invalid_twin_token"


def test_call_token_without_tenant(client: TestClient, monkeypatch, rsa_key):
    patch_jwks(monkeypatch, rsa_key)
    tok = mint_token(rsa_key, tenant_id=None)  # verifica OK mas sem tenant nas claims
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "get_feature_spec", "arguments": {"id": 1}, "_meta": {"twin_token": tok}}},
    )
    assert r.status_code == 401 and r.json()["error"] == "missing_tenant_scope"


def test_call_excluded_tool(client: TestClient, monkeypatch):
    monkeypatch.setattr(M, "_EXCLUDE_TOOLS", frozenset({"get_feature_spec"}))
    r = client.post("/mcp/tools/call", json={"params": {"name": "get_feature_spec", "arguments": {"id": 1}}})
    assert r.status_code == 403 and r.json()["error"] == "tool_excluded"


# ── _verify_inner_token (RS256 real) ──────────────────────────────────────────
def test_verify_inner_token_unconfigured():
    s = ProductManagerSettings(MCP_TWIN_AUDIENCE="", URL_ADMIN_TWIN_JWKS="")
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
    assert settings.mcp_twin_audience == "mcp:product-manager-mcp"
    assert http_app.title.startswith("product-manager-mcp")
    assert TestClient(http_app).get("/v1/health").json()["service"] == "product-manager-mcp"


# ── Execução com estado (MySQL real) ──────────────────────────────────────────
@pytest.mark.integration
@requires_mysql
async def test_dispatch_routes_all_tools(store_a):
    async def d(name, args):
        return await M._dispatch(name, args, store_a)

    # Feature Specs
    spec = (await d("save_feature_spec", {"feature": "f", "content": {"o": 1}}))["feature_spec"]
    assert (await d("list_feature_specs", {}))["total"] == 1
    assert (await d("get_feature_spec", {"id": spec["id"]}))["feature"] == "f"
    assert (await d("update_feature_spec", {"id": spec["id"], "status": "ok"}))["updated"] is True
    assert (await d("delete_feature_spec", {"id": spec["id"]}))["deleted"] is True

    # GTM Briefs
    brief = (await d("save_gtm_brief", {"product": "p", "content": {"c": ["site"]}}))["gtm_brief"]
    assert (await d("list_gtm_briefs", {}))["total"] == 1
    assert (await d("get_gtm_brief", {"id": brief["id"]}))["product"] == "p"
    assert (await d("update_gtm_brief", {"id": brief["id"], "status": "ready"}))["updated"] is True
    assert (await d("delete_gtm_brief", {"id": brief["id"]}))["deleted"] is True

    # Release Plans
    plan = (await d("save_release_plan", {"product": "p", "content": {"phases": ["ga"]}}))["release_plan"]
    assert (await d("list_release_plans", {}))["total"] == 1
    assert (await d("get_release_plan", {"id": plan["id"]}))["product"] == "p"
    assert (await d("update_release_plan", {"id": plan["id"], "status": "done"}))["updated"] is True
    assert (await d("delete_release_plan", {"id": plan["id"]}))["deleted"] is True

    # Product Visions (upsert por product)
    assert (await d("set_product_vision", {"product": "acme", "vision": "v"}))["saved"] is True
    assert (await d("list_product_visions", {}))["total"] == 1
    assert (await d("get_product_vision", {"product": "acme"}))["product"] == "acme"
    assert (await d("delete_product_vision", {"product": "acme"}))["deleted"] is True

    # Artifacts
    art = (await d("save_artifact", {"kind": "roadmap", "target": "acme", "content": "body"}))["artifact"]
    assert (await d("list_artifacts", {}))["total"] == 1
    assert (await d("get_artifact", {"id": art["id"]}))["kind"] == "roadmap"
    assert (await d("delete_artifact", {"id": art["id"]}))["deleted"] is True

    with pytest.raises(KeyError):
        await d("does_not_exist", {})


@pytest.mark.integration
@requires_mysql
async def test_dispatch_validation_paths(store_a):
    # kind inválido de artefato → erro sem persistir
    bad = await M._dispatch("save_artifact", {"kind": "nope", "target": "x", "content": "c"}, store_a)
    assert bad["error"] == "invalid_kind"
    # get de id inexistente → not_found
    missing = await M._dispatch("get_feature_spec", {"id": 999999}, store_a)
    assert missing["error"] == "not_found"


@pytest.mark.integration
@requires_mysql
async def test_run_tool_credential_zero_end_to_end(seed_platforms):
    """Caminho REAL: _run_tool -> _ensure_tenant_schema -> for_tenant (get_platform ->
    PLATFORMS) -> ProductManagerStore -> _dispatch, tudo em MySQL real."""
    M._SCHEMA_READY.discard(TENANT_A)
    settings = _test_settings()  # com ADMIN_DB_*/DB_* reais (resolve o tenant via PLATFORMS)
    saved = await M._run_tool(
        "save_feature_spec", {"feature": "e2e", "content": {"stories": 3}}, settings, TENANT_A
    )
    assert saved["saved"] is True and saved["feature_spec"]["feature"] == "e2e"
    listed = await M._run_tool("list_feature_specs", {}, settings, TENANT_A)
    assert listed["total"] == 1
    with pytest.raises(KeyError):
        await M._run_tool("nope", {}, settings, TENANT_A)
