"""Sidecar mcp_http + PEP inner-token (RS256 REAL) — §16 / Test Doubles Policy.

RS256 é real: chave gerada, token assinado, verificador real (o PyJWKClient serve a
chave pública local — sem bypass, sem HS*). Os caminhos do PEP que retornam ANTES do DB
(missing/invalid token, tenant ausente, exclude, exempt `status` compute-only) rodam via
TestClient. A execução com estado (dispatch/_run_tool) roda contra MySQL real com `await`
(mesmo event loop do teste async — os pools aiomysql são atados a esse loop).
"""

from __future__ import annotations

import json

import jwt
import pytest
from fastapi.testclient import TestClient

from src.config.settings import QASettings
from src.server import mcp_server as M

from .conftest import TENANT_A, _test_settings, mint_token, patch_jwks, requires_mysql

_ALL_TOOLS = {
    "status",
    "run_unit_tests",
    "run_e2e_tests",
    "run_api_tests",
    "generate_test_matrix",
    "screenshot_page",
    "check_accessibility",
    "visual_regression",
    "run_linter",
    "run_security_scan",
    "check_dependencies",
    "run_type_check",
    "analyze_complexity",
    "get_coverage_report",
    "generate_qa_report",
}


def _settings(**over) -> QASettings:
    return QASettings(
        MCP_TWIN_AUDIENCE="mcp:qa-mcp",
        URL_ADMIN_TWIN_JWKS="http://admin.local/.well-known/jwks.json",
        **over,
    )


@pytest.fixture()
def client() -> TestClient:
    return TestClient(M._build_http_app(_settings()))


# ── Schemas / catálogo (sem DB) ───────────────────────────────────────────────
def test_tool_count():
    assert len(M._TOOL_SCHEMAS) == 15


def test_required_fields_are_subset_of_properties():
    for name, meta in M._TOOL_SCHEMAS.items():
        props = set(meta["schema"].get("properties", {}).keys())
        required = set(meta["schema"].get("required", []))
        assert required <= props, f"{name}: required fora de properties"


# ── /v1/health ────────────────────────────────────────────────────────────────
def test_health(client: TestClient):
    r = client.get("/v1/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "service": "qa-mcp", "tools": len(M._TOOL_SCHEMAS)}


# ── /mcp/tools/list — todos os 4 campos de policy (CI-2) ──────────────────────
def test_tools_list_has_policy_fields(client: TestClient):
    tools = client.get("/mcp/tools/list").json()["result"]["tools"]
    assert {t["name"] for t in tools} == _ALL_TOOLS
    for t in tools:
        assert t["inputSchema"]["type"] == "object"
        for field in ("capability", "required_scope", "resource_type", "data_domain"):
            assert t[field], f"{t['name']} sem {field}"
        # required_scope no formato dominio:tipo:acao (3 segmentos → 2 ':')
        assert t["required_scope"].count(":") == 2
        assert t["capability"] == f"qa-mcp.{t['name']}"
        assert t["required_scope"].startswith("qa-mcp:")
    by_name = {t["name"]: t for t in tools}
    # execuções/geração usam verbo :write; análises/relatórios :read
    assert by_name["run_unit_tests"]["required_scope"].endswith(":write")
    assert by_name["screenshot_page"]["required_scope"].endswith(":write")
    assert by_name["run_linter"]["required_scope"].endswith(":read")
    assert by_name["generate_qa_report"]["required_scope"].endswith(":read")


# ── /mcp/tools/call — PEP (RS256 real), caminhos que retornam antes do DB ──────
def test_call_missing_twin_token(client: TestClient):
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "generate_qa_report", "arguments": {"repo_path": "/r"}}},
    )
    assert r.status_code == 401
    assert r.json()["error"] == "missing_twin_token"


def test_call_invalid_audience_rejected(client: TestClient, monkeypatch, rsa_key):
    patch_jwks(monkeypatch, rsa_key)
    tok = mint_token(rsa_key, aud="mcp:outro-servico")  # audiência errada → verificador real rejeita
    r = client.post(
        "/mcp/tools/call",
        json={
            "params": {
                "name": "generate_qa_report",
                "arguments": {"repo_path": "/r"},
                "_meta": {"twin_token": tok},
            }
        },
    )
    assert r.status_code == 401
    assert r.json()["error"] == "invalid_twin_token"


def test_call_token_without_jti_rejected(client: TestClient, monkeypatch, rsa_key):
    patch_jwks(monkeypatch, rsa_key)
    tok = mint_token(rsa_key, include_jti=False)  # sem jti → require falha
    r = client.post(
        "/mcp/tools/call",
        json={
            "params": {
                "name": "generate_qa_report",
                "arguments": {"repo_path": "/r"},
                "_meta": {"twin_token": tok},
            }
        },
    )
    assert r.status_code == 401
    assert r.json()["error"] == "invalid_twin_token"


def test_call_token_without_tenant(client: TestClient, monkeypatch, rsa_key):
    patch_jwks(monkeypatch, rsa_key)
    tok = mint_token(rsa_key, tenant_id=None)  # verifica OK mas sem tenant nas claims
    r = client.post(
        "/mcp/tools/call",
        json={
            "params": {
                "name": "generate_qa_report",
                "arguments": {"repo_path": "/r"},
                "_meta": {"twin_token": tok},
            }
        },
    )
    assert r.status_code == 401
    assert r.json()["error"] == "missing_tenant_scope"


def test_call_excluded_tool(client: TestClient, monkeypatch):
    monkeypatch.setattr(M, "_EXCLUDE_TOOLS", frozenset({"generate_qa_report"}))
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "generate_qa_report", "arguments": {"repo_path": "/r"}}},
    )
    assert r.status_code == 403
    assert r.json()["error"] == "tool_excluded"


# ── /mcp/tools/call — tool exempt (status) compute-only, sem token → 200 ───────
def test_call_exempt_status_without_token(client: TestClient):
    r = client.post("/mcp/tools/call", json={"params": {"name": "status", "arguments": {}}})
    assert r.status_code == 200
    payload = json.loads(r.json()["result"]["content"][0]["text"])
    assert payload["service"] == "qa-mcp"
    assert payload["tools"] == len(M._TOOL_SCHEMAS)


# ── _status (compute-only) ────────────────────────────────────────────────────
def test_status_compute_only():
    out = M._status()
    assert out["service"] == "qa-mcp"
    assert out["status"] == "ok"
    assert out["tools"] == len(M._TOOL_SCHEMAS)


# ── _verify_inner_token (RS256 real) ──────────────────────────────────────────
def test_verify_inner_token_unconfigured():
    s = QASettings(mcp_twin_audience="", url_admin_twin_jwks="")
    with pytest.raises(PermissionError):
        M._verify_inner_token("tok", s)


def test_verify_inner_token_real_rs256(monkeypatch, rsa_key):
    patch_jwks(monkeypatch, rsa_key)
    claims = M._verify_inner_token(mint_token(rsa_key, tenant_id="T-9"), _settings())
    assert claims["tenant_id"] == "T-9"
    with pytest.raises(jwt.InvalidAudienceError):
        M._verify_inner_token(mint_token(rsa_key, aud="mcp:x"), _settings())


def test_verify_inner_token_missing_jti(monkeypatch, rsa_key):
    patch_jwks(monkeypatch, rsa_key)
    with pytest.raises(jwt.MissingRequiredClaimError):
        M._verify_inner_token(mint_token(rsa_key, include_jti=False), _settings())


# ── build_server (3-tuple; stdio recusa fail-closed exceto status) ────────────
def test_build_server_smoke(monkeypatch):
    monkeypatch.setattr(M, "get_settings", _settings)
    server, settings, http_app = M.build_server()
    assert server is not None
    assert settings.mcp_twin_audience == "mcp:qa-mcp"
    assert http_app.title.startswith("qa-mcp")
    resp = TestClient(http_app).get("/v1/health")
    assert resp.json()["service"] == "qa-mcp"


def test_main_http_only(monkeypatch):
    monkeypatch.setenv("MCP_HTTP_ONLY", "1")
    monkeypatch.setattr(M, "get_settings", _settings)
    called: dict = {}

    import uvicorn

    def _fake_run(app, **kwargs):
        called["port"] = kwargs.get("port")

    monkeypatch.setattr(uvicorn, "run", _fake_run)
    M.main()
    assert called["port"] == 7100


# ── Execução com estado (MySQL real) ──────────────────────────────────────────
@pytest.mark.integration
@requires_mysql
async def test_dispatch_status_and_unknown(store_a):
    s = _settings()
    out = await M._dispatch("status", {}, s, store_a)
    assert out["service"] == "qa-mcp"
    with pytest.raises(KeyError):
        await M._dispatch("does_not_exist", {}, s, store_a)


@pytest.mark.integration
@requires_mysql
async def test_dispatch_routes_persisting_tools(store_a):
    """Roteamento de _dispatch para tools que persistem (store real)."""
    from unittest.mock import patch

    s = _settings()

    # generate_qa_report: só lê o histórico (vazio) + persiste o próprio report.
    rep = await M._dispatch("generate_qa_report", {"repo_path": "/x"}, s, store_a)
    assert rep["grade"] == "F"

    # run_linter roteia e persiste (ruff mockado).
    with patch("src.tools.analysis_tool._run_subprocess", return_value=(0, "[]", "")):
        lint = await M._dispatch(
            "run_linter",
            {"repo_path": "/tmp/does-not-matter"},
            s,
            store_a,  # noqa: S108
        )
    assert lint["tool"] == "ruff"
    assert "run_id" in lint


@pytest.mark.integration
@requires_mysql
async def test_run_tool_credential_zero_end_to_end(seed_platforms):
    """Caminho REAL: _run_tool -> _ensure_tenant_schema -> for_tenant (get_platform ->
    PLATFORMS) -> QAStore -> _dispatch, tudo em MySQL real."""
    M._SCHEMA_READY.discard(TENANT_A)
    settings = _test_settings()  # com ADMIN_DB_*/DB_* reais (resolve o tenant via PLATFORMS)
    result = await M._run_tool("generate_qa_report", {"repo_path": "/e2e"}, settings, TENANT_A)
    assert result["grade"] == "F"  # histórico vazio
    assert "run_id" in result
    with pytest.raises(KeyError):
        await M._run_tool("nope", {}, settings, TENANT_A)
