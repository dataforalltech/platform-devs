"""Sidecar HTTP governado (STD-MCP-001 / STD-SEC-006): catálogo com policy, verificação
RS256 real do inner token, denylist e dispatch storeless — sem tocar o MySQL.

Estes testes exercitam a borda gateway (token/tenant/policy) e as tools storeless
(status/get_physical_info), que não abrem sessão de tenant. O caminho DB-backed é
coberto por test_store.py / test_tools.py (MySQL real)."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

import src.server.mcp_server as M
from src.config.settings import Settings
from src.knowledge.encryptor import Encryptor
from src.server.mcp_server import (
    _EXCLUDE_TOOLS,
    _POLICY_FIELDS,
    _TOOL_SCHEMAS,
    _build_encryptor,
    _build_http_app,
    _dispatch,
    _dispatch_storeless,
    _verify_inner_token,
)

from .conftest import TENANT_A, _test_settings, mint_token, patch_jwks, requires_mysql

_FERNET = Encryptor.generate_key()


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        MCP_TWIN_AUDIENCE="mcp:config-mcp",
        URL_ADMIN_TWIN_JWKS="http://admin.local/jwks.json",
        CONFIG_MCP_MASTER_KEY=_FERNET,
    )


def _client() -> TestClient:
    settings = _settings()
    enc = Encryptor(settings.resolve_master_key())
    return TestClient(_build_http_app(settings, enc))


def _decode(resp) -> dict:
    body = resp.json()
    return json.loads(body["result"]["content"][0]["text"])


def test_health() -> None:
    resp = _client().get("/v1/health")
    assert resp.status_code == 200
    assert resp.json()["service"] == "config-mcp"


def test_list_tools_carries_policy_fields() -> None:
    resp = _client().get("/mcp/tools/list")
    assert resp.status_code == 200
    tools = resp.json()["result"]["tools"]
    assert {entry["name"] for entry in tools} == set(_TOOL_SCHEMAS) - _EXCLUDE_TOOLS
    for entry in tools:
        assert entry["inputSchema"]["type"] == "object"
        for field in _POLICY_FIELDS:
            assert entry[field]


def test_status_is_exempt_no_token() -> None:
    resp = _client().post("/mcp/tools/call", json={"params": {"name": "status", "arguments": {}}})
    assert resp.status_code == 200
    payload = _decode(resp)
    assert payload["status"] == "ok"
    assert payload["service"] == "config-mcp"


def test_excluded_tool_is_denied() -> None:
    # get_credential devolve segredo em claro → nunca sai pelo gateway (fail-safe).
    assert "get_credential" in _EXCLUDE_TOOLS
    assert {"set_credential", "set_credential_secure", "read_env_file"} <= _EXCLUDE_TOOLS
    resp = _client().post(
        "/mcp/tools/call",
        json={"params": {"name": "get_credential", "arguments": {"namespace": "x", "key": "y"}}},
    )
    assert resp.status_code == 403
    assert resp.json()["error"] == "tool_excluded"


def test_missing_token_rejected() -> None:
    resp = _client().post("/mcp/tools/call", json={"params": {"name": "get_physical_info", "arguments": {}}})
    assert resp.status_code == 401
    assert resp.json()["error"] == "missing_twin_token"


def test_invalid_audience_rejected(monkeypatch, rsa_key) -> None:
    patch_jwks(monkeypatch, rsa_key)
    bad = mint_token(rsa_key, aud="mcp:outra")  # audiência divergente → rejeita
    resp = _client().post(
        "/mcp/tools/call",
        json={"params": {"name": "get_physical_info", "arguments": {}, "_meta": {"twin_token": bad}}},
    )
    assert resp.status_code == 401
    assert resp.json()["error"] == "invalid_twin_token"


def test_missing_tenant_scope_rejected(monkeypatch, rsa_key) -> None:
    patch_jwks(monkeypatch, rsa_key)
    no_tenant = mint_token(rsa_key, tenant_id=None)  # token válido, sem tenant_id
    resp = _client().post(
        "/mcp/tools/call",
        json={"params": {"name": "get_physical_info", "arguments": {}, "_meta": {"twin_token": no_tenant}}},
    )
    assert resp.status_code == 401
    assert resp.json()["error"] == "missing_tenant_scope"


def test_missing_jti_rejected(monkeypatch, rsa_key) -> None:
    # Inner token sem jti → options require:[jti] falha na verificação RS256 REAL
    # (MissingRequiredClaimError) → 401. Rejeitado no PEP, antes de qualquer DB.
    patch_jwks(monkeypatch, rsa_key)
    no_jti = mint_token(rsa_key, include_jti=False)
    resp = _client().post(
        "/mcp/tools/call",
        json={"params": {"name": "get_physical_info", "arguments": {}, "_meta": {"twin_token": no_jti}}},
    )
    assert resp.status_code == 401
    assert resp.json()["error"] == "invalid_twin_token"


def test_expired_token_rejected(monkeypatch, rsa_key) -> None:
    # exp no passado → ExpiredSignatureError na verificação RS256 REAL → 401.
    # Rejeitado no PEP, antes de qualquer DB.
    patch_jwks(monkeypatch, rsa_key)
    expired = mint_token(rsa_key, exp_delta=-10)
    resp = _client().post(
        "/mcp/tools/call",
        json={"params": {"name": "get_physical_info", "arguments": {}, "_meta": {"twin_token": expired}}},
    )
    assert resp.status_code == 401
    assert resp.json()["error"] == "invalid_twin_token"


def test_valid_token_storeless_dispatch(monkeypatch, rsa_key) -> None:
    # Token RS256 válido → get_physical_info (storeless) roda sem abrir sessão de tenant.
    patch_jwks(monkeypatch, rsa_key)
    good = mint_token(rsa_key)
    resp = _client().post(
        "/mcp/tools/call",
        json={"params": {"name": "get_physical_info", "arguments": {}, "_meta": {"twin_token": good}}},
    )
    assert resp.status_code == 200
    payload = _decode(resp)
    assert payload["success"] is True
    assert "cpu" in payload


def test_unknown_tool_returns_404(monkeypatch, rsa_key) -> None:
    patch_jwks(monkeypatch, rsa_key)
    good = mint_token(rsa_key)
    resp = _client().post(
        "/mcp/tools/call",
        json={"params": {"name": "does_not_exist", "arguments": {}, "_meta": {"twin_token": good}}},
    )
    assert resp.status_code == 404
    assert resp.json()["error"] == "unknown_tool"


def test_http_call_internal_error(monkeypatch, rsa_key) -> None:
    # Falha interna de execução (não-KeyError) → 200 com payload {error: internal_error}.
    patch_jwks(monkeypatch, rsa_key)

    async def _boom(*_a, **_k):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(M, "_run_tool", _boom)
    good = mint_token(rsa_key)
    resp = _client().post(
        "/mcp/tools/call",
        json={"params": {"name": "list_environments", "arguments": {}, "_meta": {"twin_token": good}}},
    )
    assert resp.status_code == 200
    payload = _decode(resp)
    assert payload["error"] == "internal_error"
    assert payload["detail"] == "kaboom"


def test_shutdown_closes_pools() -> None:
    # O context manager do TestClient dispara o evento de shutdown (close_tenant_pools).
    with _client() as client:
        assert client.get("/v1/health").status_code == 200


# ── Helpers puros (sem DB) ──────────────────────────────────────────────────────
def test_verify_inner_token_unconfigured() -> None:
    s = Settings(_env_file=None, MCP_TWIN_AUDIENCE="", URL_ADMIN_TWIN_JWKS="")
    with pytest.raises(PermissionError):
        _verify_inner_token("tok", s)


def test_build_encryptor_valid_roundtrip() -> None:
    enc = _build_encryptor(_settings())
    assert enc.decrypt(enc.encrypt("x")) == "x"


def test_build_encryptor_invalid_key_aborts(monkeypatch) -> None:
    monkeypatch.delenv("VAULT_ADDR", raising=False)
    bad = Settings(
        _env_file=None,
        MCP_TWIN_AUDIENCE="mcp:config-mcp",
        CONFIG_MCP_MASTER_KEY="not-a-valid-fernet-key",
    )
    with pytest.raises(SystemExit):
        _build_encryptor(bad)


async def test_dispatch_storeless_status_and_unknown() -> None:
    payload = await _dispatch_storeless("status")
    assert payload["status"] == "ok"
    assert payload["service"] == "config-mcp"
    with pytest.raises(KeyError):
        await _dispatch_storeless("does_not_exist")


def test_build_server_smoke(monkeypatch) -> None:
    monkeypatch.setattr(M, "get_settings", lambda: _settings())
    server, settings, http_app = M.build_server()
    assert server is not None
    assert settings.mcp_twin_audience == "mcp:config-mcp"
    assert http_app.title.startswith("config-mcp")
    assert TestClient(http_app).get("/v1/health").json()["service"] == "config-mcp"


# ── Dispatch DB-backed (MySQL real, store do tenant) ────────────────────────────
@pytest.mark.integration
@requires_mysql
async def test_dispatch_routes_credentials_and_tenants(store_a, monkeypatch) -> None:
    import getpass

    monkeypatch.setattr(getpass, "getpass", lambda prompt="": "sekret")
    monkeypatch.setattr("src.tools.tenant_tool._get_twin_tenant_id", lambda: None)

    async def d(name, args):
        return await _dispatch(name, args, store_a)

    assert (
        await d(
            "set_credential", {"namespace": "credentials.acr", "key": "U", "value": "v", "description": "x"}
        )
    )["success"] is True
    assert (await d("get_credential", {"namespace": "credentials.acr", "key": "U"}))["value"] == "v"
    assert (await d("set_credential_secure", {"namespace": "credentials.acr", "key": "P"}))["success"] is True
    assert "credentials.acr" in (await d("list_credentials", {}))["namespaces"]
    assert (await d("delete_credential", {"namespace": "credentials.acr", "key": "U"}))["deleted"] is True

    # Tenants: com tenant_id → real; sem → missing_tenant (INV-3).
    assert (await d("set_tenant_config", {"tenant_id": "tt", "key": "K", "value": "V"}))["success"] is True
    assert (await d("get_tenant_config", {"tenant_id": "tt"}))["found"] is True
    assert (await d("get_tenant_config", {}))["error"] == "missing_tenant"
    assert (await d("set_tenant_config", {"key": "K", "value": "V"}))["error"] == "missing_tenant"
    assert "tt" in (await d("list_tenants", {}))["tenants"]
    assert (await d("get_session_tenant_config", {}))["found"] is False
    with pytest.raises(KeyError):
        await d("does_not_exist", {})


@pytest.mark.integration
@requires_mysql
async def test_dispatch_routes_env_and_workspace(store_a, tmp_path) -> None:
    async def d(name, args):
        return await _dispatch(name, args, store_a)

    assert (await d("set_env_var", {"environment": "dev", "key": "A", "value": "1"}))["success"] is True
    assert (await d("get_env_config", {"environment": "dev"}))["config"]["A"] == "1"
    assert "dev" in (await d("list_environments", {}))["environments"]

    envpath = str(tmp_path / ".env.dev")
    assert (await d("sync_env_file", {"target_path": envpath, "environment": "dev"}))["success"] is True

    readf = tmp_path / ".env.read"
    readf.write_text("X=9\n", encoding="utf-8")
    assert (await d("read_env_file", {"path": str(readf)}))["variables"]["X"] == "9"

    auditdir = tmp_path / "audit"
    auditdir.mkdir()
    (auditdir / ".env.test").write_text("API_KEY=hardcodedvalue\n", encoding="utf-8")
    assert (await d("audit_env_files", {"directory": str(auditdir)}))["hardcoded_secrets_count"] == 1

    redf = tmp_path / ".env.red"
    redf.write_text("API_KEY=zzsecretzz\n", encoding="utf-8")
    assert (await d("redact_env_secrets", {"paths": [str(redf)]}))["total_changes"] == 1

    pushf = tmp_path / ".env.push"
    pushf.write_text("PUSHED=1\n", encoding="utf-8")
    assert (await d("push_env_to_store", {"path": str(pushf), "environment": "stage"}))["pushed"] == 1

    assert (await d("set_workspace_config", {"key": "PYTHON_BIN", "value": "py"}))["action"] == "set"
    assert (await d("get_workspace_config", {"key": "PYTHON_BIN"}))["value"] == "py"
    assert (await d("get_workspace_config", {}))["namespace"] == "workspace"
    assert (await d("list_workspace_config", {}))["namespace"] == "workspace"


# ── _run_tool credencial-zero end-to-end (for_tenant → PLATFORMS → store) ────────
@pytest.mark.integration
@requires_mysql
async def test_run_tool_credential_zero_end_to_end(seed_platforms) -> None:
    M._SCHEMA_READY.discard(TENANT_A)
    settings = _test_settings()  # ADMIN_DB_*/DB_* reais → resolve o tenant via PLATFORMS
    enc = Encryptor(settings.resolve_master_key())

    ok = await M._run_tool(
        "set_env_var", {"environment": "dev", "key": "K", "value": "V"}, settings, TENANT_A, enc
    )
    assert ok["success"] is True
    got = await M._run_tool("get_env_config", {"environment": "dev"}, settings, TENANT_A, enc)
    assert got["config"]["K"] == "V"

    # storeless via _run_tool (não abre sessão de tenant)
    st = await M._run_tool("status", {}, settings, TENANT_A, enc)
    assert st["status"] == "ok"

    with pytest.raises(KeyError):
        await M._run_tool("does_not_exist", {}, settings, TENANT_A, enc)


@pytest.mark.integration
@requires_mysql
async def test_run_tool_unknown_before_tenant() -> None:
    # name fora do catálogo → KeyError antes de qualquer resolução de tenant.
    settings = _test_settings()
    enc = Encryptor(settings.resolve_master_key())
    with pytest.raises(KeyError):
        await M._run_tool("ghost_tool", {}, settings, "irrelevant", enc)
