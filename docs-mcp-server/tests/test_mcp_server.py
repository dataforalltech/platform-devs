"""Sidecar mcp_http + PEP inner-token (RS256 REAL) — §16 / Test Doubles Policy.

RS256 é real: chave gerada, token assinado, verificador real (o PyJWKClient serve a
chave pública local — sem bypass, sem HS*). O caminho de execução com estado (dispatch /
run_tool / unknown) roda contra MySQL real via `_run_tool`/`_dispatch`.
"""

from __future__ import annotations

import asyncio
import json

import jwt
import mcp.types as mtypes
import pytest
from fastapi.testclient import TestClient

from src.config.settings import DocsSettings
from src.server import mcp_server as M

from .conftest import TENANT_A, _test_settings, mint_token, patch_jwks, requires_mysql

_EXPECTED_TOOLS = {
    "scan_docs",
    "search_docs",
    "get_doc_tree",
    "validate_doc",
    "check_links",
    "check_required_docs",
    "lint_markdown",
    "list_templates",
    "generate_doc",
    "check_doc_standards",
    "audit_repo",
    "find_stale_docs",
    "get_audit_history",
    "generate_doc_report",
}


def _settings(**over) -> DocsSettings:
    return DocsSettings(
        MCP_TWIN_AUDIENCE="mcp:docs-mcp",
        URL_ADMIN_TWIN_JWKS="http://admin.local/jwks.json",
        **over,
    )


@pytest.fixture()
def client() -> TestClient:
    return TestClient(M._build_http_app(_settings()))


# ── Schemas / catálogo (sem DB) ───────────────────────────────────────────────
def test_tool_count():
    assert len(M._TOOL_SCHEMAS) == 14
    assert set(M._TOOL_SCHEMAS.keys()) == _EXPECTED_TOOLS


def test_required_fields_are_subset_of_properties():
    for name, meta in M._TOOL_SCHEMAS.items():
        props = set(meta["schema"].get("properties", {}).keys())
        required = set(meta["schema"].get("required", []))
        assert required <= props, f"{name}: required fora de properties"


def test_health(client: TestClient):
    r = client.get("/v1/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "service": "docs-mcp", "tools": 14}


def test_tools_list_has_policy_fields(client: TestClient):
    tools = client.get("/mcp/tools/list").json()["result"]["tools"]
    assert {t["name"] for t in tools} == _EXPECTED_TOOLS
    for t in tools:
        assert t["inputSchema"]["type"] == "object"
        for field in ("capability", "required_scope", "resource_type", "data_domain"):
            assert t[field], f"{t['name']} sem {field}"
        assert t["required_scope"].count(":") == 2
        assert t["capability"] == f"docs-mcp.{t['name']}"
    by_name = {t["name"]: t for t in tools}
    # geração de artefato usa verbo :write; análise/scan/validação é :read
    assert by_name["generate_doc"]["required_scope"].endswith(":write")
    assert by_name["scan_docs"]["required_scope"].endswith(":read")
    assert by_name["validate_doc"]["required_scope"].endswith(":read")


# ── /mcp/tools/call — PEP (RS256 real), caminhos que retornam antes do DB ──────
def test_call_missing_twin_token(client: TestClient):
    r = client.post(
        "/mcp/tools/call", json={"params": {"name": "scan_docs", "arguments": {"repo_path": "/x"}}}
    )
    assert r.status_code == 401 and r.json()["error"] == "missing_twin_token"


def test_call_invalid_audience_rejected(client: TestClient, monkeypatch, rsa_key):
    patch_jwks(monkeypatch, rsa_key)
    tok = mint_token(rsa_key, aud="mcp:outro-servico")  # audiência errada → verificador real rejeita
    r = client.post(
        "/mcp/tools/call",
        json={
            "params": {"name": "scan_docs", "arguments": {"repo_path": "/x"}, "_meta": {"twin_token": tok}}
        },
    )
    assert r.status_code == 401 and r.json()["error"] == "invalid_twin_token"


def test_call_token_without_jti_rejected(client: TestClient, monkeypatch, rsa_key):
    patch_jwks(monkeypatch, rsa_key)
    tok = mint_token(rsa_key, include_jti=False)  # sem jti → require falha
    r = client.post(
        "/mcp/tools/call",
        json={
            "params": {"name": "scan_docs", "arguments": {"repo_path": "/x"}, "_meta": {"twin_token": tok}}
        },
    )
    assert r.status_code == 401 and r.json()["error"] == "invalid_twin_token"


def test_call_token_without_tenant(client: TestClient, monkeypatch, rsa_key):
    patch_jwks(monkeypatch, rsa_key)
    tok = mint_token(rsa_key, tenant_id=None)  # verifica OK mas sem tenant nas claims
    r = client.post(
        "/mcp/tools/call",
        json={
            "params": {"name": "scan_docs", "arguments": {"repo_path": "/x"}, "_meta": {"twin_token": tok}}
        },
    )
    assert r.status_code == 401 and r.json()["error"] == "missing_tenant_scope"


def test_call_excluded_tool(client: TestClient, monkeypatch):
    monkeypatch.setattr(M, "_EXCLUDE_TOOLS", frozenset({"scan_docs"}))
    r = client.post(
        "/mcp/tools/call", json={"params": {"name": "scan_docs", "arguments": {"repo_path": "/x"}}}
    )
    assert r.status_code == 403 and r.json()["error"] == "tool_excluded"


# ── _verify_inner_token (RS256 real) ──────────────────────────────────────────
def test_verify_inner_token_unconfigured():
    s = DocsSettings(MCP_TWIN_AUDIENCE="", URL_ADMIN_TWIN_JWKS="")
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
    assert settings.mcp_twin_audience == "mcp:docs-mcp"
    assert http_app.title.startswith("docs-mcp")
    assert TestClient(http_app).get("/v1/health").json()["service"] == "docs-mcp"

    handler = server.request_handlers[mtypes.ListToolsRequest]
    res = asyncio.run(handler(mtypes.ListToolsRequest(method="tools/list")))
    assert len(res.root.tools) == 14

    # stdio recusa fail-closed (sem tenant): não despacha, retorna tenant_context_required.
    call = server.request_handlers[mtypes.CallToolRequest]
    req = mtypes.CallToolRequest(
        method="tools/call",
        params=mtypes.CallToolRequestParams(name="list_templates", arguments={}),
    )
    out = asyncio.run(call(req))
    assert json.loads(out.root.content[0].text)["error"] == "tenant_context_required"


# ── _dispatch — roteamento hermético (compute-only) + KeyError ────────────────
async def test_dispatch_list_templates_and_keyerror():
    s = _settings()
    # list_templates é compute-only (ignora o store) → store=None é seguro.
    assert (await M._dispatch("list_templates", {}, s, None))["count"] == 6
    with pytest.raises(KeyError):
        await M._dispatch("unknown", {}, s, None)


# ── Execução com estado (MySQL real) ──────────────────────────────────────────
@pytest.mark.integration
@requires_mysql
async def test_dispatch_routes_db_tools(store_a, tmp_path):
    s = _settings()
    (tmp_path / "README.md").write_text("# My Service\n\n## Installation\n\nx\n\n## Usage\n\ny\n", "utf-8")

    async def d(name, args):
        return await M._dispatch(name, args, s, store_a)

    scanned = await d("scan_docs", {"repo_path": str(tmp_path)})
    assert scanned["total"] >= 1
    audited = await d("audit_repo", {"repo_path": str(tmp_path)})
    assert "audit_id" in audited
    history = await d("get_audit_history", {"repo_path": str(tmp_path)})
    assert history["total"] >= 1
    report = await d("generate_doc_report", {"repo_path": str(tmp_path)})
    assert "score" in report and "trend" in report


@pytest.mark.integration
@requires_mysql
async def test_run_tool_credential_zero_end_to_end(seed_platforms):
    """Caminho REAL: _run_tool -> _ensure_tenant_schema -> for_tenant (get_platform ->
    PLATFORMS) -> DocsStore -> _dispatch, tudo em MySQL real."""
    M._SCHEMA_READY.discard(TENANT_A)
    settings = _test_settings()  # com ADMIN_DB_*/DB_* reais (resolve o tenant via PLATFORMS)
    result = await M._run_tool("get_audit_history", {}, settings, TENANT_A)
    # Valida o caminho credencial-zero (for_tenant→PLATFORMS→store retornou uma resposta
    # bem-formada). A contagem exata é coberta pelos testes de store — o tenant DB é
    # compartilhado dentro da suíte (seed_platforms não trunca), então não é pristino aqui.
    assert isinstance(result["total"], int) and "audits" in result
    with pytest.raises(KeyError):
        await M._run_tool("nope", {}, settings, TENANT_A)
