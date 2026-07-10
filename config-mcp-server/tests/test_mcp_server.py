"""Testes do sidecar mcp_http + PEP inner-token (STD-MCP-001 / STD-SEC-006).

Cobre: /v1/health, /mcp/tools/list (campos de policy), /mcp/tools/call
(missing/invalid token, exempt, tenant das claims → INV-3, exclude, unknown) e
_verify_inner_token não configurado. O PyJWKClient/JWKS é sempre mockado — os
testes nunca fazem I/O de rede (FID-01 / Test Doubles Policy). O ConfigStore é
sempre um store encriptado efêmero em tmp_path.
"""

from __future__ import annotations

import json

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from src.config.settings import Settings
from src.knowledge.encryptor import Encryptor
from src.knowledge.store import ConfigStore
from src.server import mcp_server as M


def _settings() -> Settings:
    return Settings(
        MCP_TWIN_AUDIENCE="mcp:config-mcp",
        URL_ADMIN_TWIN_JWKS="http://admin.local/.well-known/jwks.json",
        _env_file=None,
    )


@pytest.fixture()
def app_store(tmp_path) -> ConfigStore:
    enc = Encryptor(Fernet.generate_key().decode())
    return ConfigStore(str(tmp_path / "s.enc.json"), enc)


@pytest.fixture()
def client(app_store: ConfigStore) -> TestClient:
    return TestClient(M._build_http_app(_settings(), app_store))


# ── /v1/health ────────────────────────────────────────────────────────────────
def test_health(client: TestClient):
    r = client.get("/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["service"] == "config-mcp"
    assert body["tools"] == len(M._TOOL_SCHEMAS)


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
        assert t["capability"] == f"config-mcp.{t['name']}"
    by_name = {t["name"]: t for t in tools}
    assert by_name["set_credential"]["required_scope"].endswith(":write")
    assert by_name["get_env_config"]["required_scope"].endswith(":read")
    assert by_name["status"]["required_scope"] == "config-mcp:status:read"


# ── /mcp/tools/call — tool exempt (sem token) ─────────────────────────────────
def test_call_exempt_status_without_token(client: TestClient):
    r = client.post("/mcp/tools/call", json={"params": {"name": "status", "arguments": {}}})
    assert r.status_code == 200
    text = r.json()["result"]["content"][0]["text"]
    payload = json.loads(text)
    assert payload["status"] == "ok"
    assert payload["service"] == "config-mcp"


# ── /mcp/tools/call — sem inner token → 401 ───────────────────────────────────
def test_call_missing_twin_token(client: TestClient):
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "list_environments", "arguments": {}}},
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
                "name": "list_environments",
                "arguments": {},
                "_meta": {"twin_token": "tok"},
            }
        },
    )
    assert r.status_code == 401
    assert r.json()["error"] == "invalid_twin_token"


# ── /mcp/tools/call — token válido despacha tool normal ───────────────────────
def test_call_valid_token_dispatches(client: TestClient, app_store, monkeypatch):
    monkeypatch.setattr(M, "_verify_inner_token", lambda _t, _s: {"tenant_id": "T", "jti": "j"})
    app_store.set("credentials.acr", "ACR_USERNAME", "u")
    r = client.post(
        "/mcp/tools/call",
        json={
            "params": {
                "name": "list_credentials",
                "arguments": {"namespace": "credentials.acr"},
                "_meta": {"twin_token": "tok"},
            }
        },
    )
    assert r.status_code == 200
    payload = json.loads(r.json()["result"]["content"][0]["text"])
    assert "ACR_USERNAME" in payload["namespaces"]["credentials.acr"]


# ── /mcp/tools/call — token válido injeta tenant das claims (INV-3) ────────────
def test_call_valid_token_injects_tenant_from_claims(client: TestClient, app_store, monkeypatch):
    monkeypatch.setattr(M, "_verify_inner_token", lambda _t, _s: {"tenant_id": "T-42", "jti": "j"})
    r = client.post(
        "/mcp/tools/call",
        json={
            "params": {
                "name": "set_tenant_config",
                # tenant do cliente deve ser IGNORADO/sobrescrito pelas claims
                "arguments": {"key": "DB", "value": "v", "tenant_id": "ATTACKER"},
                "_meta": {"twin_token": "tok"},
            }
        },
    )
    assert r.status_code == 200
    # gravado sob o tenant das claims (T-42), nunca sob o do cliente (ATTACKER)
    assert app_store.get("tenants.T-42", "DB") == "v"
    assert app_store.get("tenants.ATTACKER", "DB") is None


# ── /mcp/tools/call — token sem tenant nas claims → 401 ───────────────────────
def test_call_valid_token_without_tenant(client: TestClient, monkeypatch):
    monkeypatch.setattr(M, "_verify_inner_token", lambda _t, _s: {"jti": "j"})
    r = client.post(
        "/mcp/tools/call",
        json={
            "params": {
                "name": "list_environments",
                "arguments": {},
                "_meta": {"twin_token": "t"},
            }
        },
    )
    assert r.status_code == 401
    assert r.json()["error"] == "missing_tenant_scope"


# ── /mcp/tools/call — denylist (exclude: retorna segredo) → 403 ───────────────
def test_call_excluded_secret_tool(client: TestClient):
    # get_credential está em _EXCLUDE_TOOLS (devolve segredo em claro)
    r = client.post(
        "/mcp/tools/call",
        json={
            "params": {
                "name": "get_credential",
                "arguments": {"namespace": "credentials.acr", "key": "ACR_PASSWORD"},
                "_meta": {"twin_token": "tok"},
            }
        },
    )
    assert r.status_code == 403
    assert r.json()["error"] == "tool_excluded"


def test_exclude_set_defaults():
    assert "get_credential" in M._EXCLUDE_TOOLS
    assert "set_credential_secure" in M._EXCLUDE_TOOLS


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
def test_call_internal_error_payload(client: TestClient, monkeypatch):
    monkeypatch.setattr(M, "_verify_inner_token", lambda _t, _s: {"tenant_id": "T"})

    def _boom(_name, _args, _store):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(M, "_dispatch", _boom)
    r = client.post(
        "/mcp/tools/call",
        json={
            "params": {
                "name": "list_environments",
                "arguments": {},
                "_meta": {"twin_token": "t"},
            }
        },
    )
    assert r.status_code == 200
    payload = json.loads(r.json()["result"]["content"][0]["text"])
    assert payload["error"] == "internal_error"


# ── _dispatch cobre todas as tools + KeyError ─────────────────────────────────
def test_dispatch_routes_status_and_lists(app_store):
    assert M._dispatch("status", {}, app_store)["status"] == "ok"
    assert "namespaces" in M._dispatch("list_credentials", {}, app_store)
    assert "environments" in M._dispatch("list_environments", {}, app_store)
    assert "tenants" in M._dispatch("list_tenants", {}, app_store)
    assert "config" in M._dispatch("list_workspace_config", {}, app_store)
    assert "success" in M._dispatch("get_physical_info", {}, app_store)
    with pytest.raises(KeyError):
        M._dispatch("unknown", {}, app_store)


def test_dispatch_credentials_env_workspace_roundtrip(app_store):
    assert M._dispatch(
        "set_credential",
        {"namespace": "credentials.gh", "key": "T", "value": "v"},
        app_store,
    )["success"]
    got = M._dispatch("get_credential", {"namespace": "credentials.gh", "key": "T"}, app_store)
    assert got["value"] == "v"
    assert M._dispatch("delete_credential", {"namespace": "credentials.gh", "key": "T"}, app_store)["deleted"]
    assert M._dispatch("set_env_var", {"environment": "dev", "key": "A", "value": "1"}, app_store)["success"]
    assert M._dispatch("get_env_config", {"environment": "dev"}, app_store)["config"]["A"] == "1"
    assert (
        M._dispatch("set_workspace_config", {"key": "EDITOR", "value": "vim"}, app_store)["key"] == "EDITOR"
    )
    assert M._dispatch("get_workspace_config", {"key": "EDITOR"}, app_store)["value"] == "vim"


def test_dispatch_credential_secure(app_store, monkeypatch):
    import getpass

    monkeypatch.setattr(getpass, "getpass", lambda prompt="": "s3cr3t")
    out = M._dispatch("set_credential_secure", {"namespace": "credentials.e2e", "key": "P"}, app_store)
    assert out["success"] is True
    assert app_store.get("credentials.e2e", "P") == "s3cr3t"


def test_dispatch_env_file_tools(app_store, tmp_path):
    envf = tmp_path / ".env.dev"
    envf.write_text("DATABASE_URL=postgres://x\nAPI_TOKEN=abcd1234\n", encoding="utf-8")
    read = M._dispatch("read_env_file", {"path": str(envf)}, app_store)
    assert read["variables"]["DATABASE_URL"] == "postgres://x"
    audit = M._dispatch("audit_env_files", {"directory": str(tmp_path)}, app_store)
    assert audit["hardcoded_secrets_count"] >= 1
    pushed = M._dispatch("push_env_to_store", {"path": str(envf), "environment": "dev"}, app_store)
    assert pushed["pushed"] >= 1
    redact = M._dispatch("redact_env_secrets", {"paths": [str(envf)], "dry_run": True}, app_store)
    assert redact["dry_run"] is True
    synced = M._dispatch(
        "sync_env_file",
        {"target_path": str(tmp_path / "out.env"), "environment": "dev"},
        app_store,
    )
    assert synced["success"] is True


def test_dispatch_tenant_tools(app_store):
    # tenant_id injetado (INV-3): presente → grava/lê
    assert M._dispatch("set_tenant_config", {"tenant_id": "T1", "key": "DB", "value": "v"}, app_store)[
        "success"
    ]
    got = M._dispatch("get_tenant_config", {"tenant_id": "T1"}, app_store)
    assert got["found"] is True and got["config"]["DB"] == "v"
    # sem tenant_id → erro claro (não grava em tenants.None)
    assert (
        M._dispatch("set_tenant_config", {"key": "X", "value": "y"}, app_store)["error"] == "missing_tenant"
    )
    assert M._dispatch("get_tenant_config", {}, app_store)["error"] == "missing_tenant"


def test_dispatch_session_tenant(app_store, monkeypatch):
    import src.tools.tenant_tool as tt

    monkeypatch.setattr(tt, "_get_twin_tenant_id", lambda: None)
    res = M._dispatch("get_session_tenant_config", {}, app_store)
    assert res["found"] is False


# ── stdio call_tool handler (fábrica build_server) ────────────────────────────
def test_build_server_and_stdio_handlers(tmp_path, monkeypatch):
    monkeypatch.delenv("MCP_TWIN_AUDIENCE", raising=False)
    monkeypatch.setenv("CONFIG_MCP_MASTER_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("CONFIG_MCP_STORE_PATH", str(tmp_path / "boot.enc.json"))
    from src.config import settings as settings_mod

    settings_mod.get_settings.cache_clear()
    server, settings, http_app = M.build_server()
    assert server is not None
    assert settings.mcp_twin_audience == "mcp:config-mcp"
    assert http_app.title.startswith("config-mcp")

    # Exercita os handlers registrados no Server de baixo nível (stdio).
    list_handler = server.request_handlers
    assert list_handler  # smoke: handlers registrados
    settings_mod.get_settings.cache_clear()


# ── _verify_inner_token não configurado → PermissionError (fail-closed) ────────
def test_verify_inner_token_unconfigured():
    s = Settings(MCP_TWIN_AUDIENCE="", URL_ADMIN_TWIN_JWKS="", _env_file=None)
    with pytest.raises(PermissionError):
        M._verify_inner_token("tok", s)


def test_build_store_invalid_key_exits(monkeypatch):
    bad = Settings(CONFIG_MCP_MASTER_KEY="not-a-valid-fernet-key", _env_file=None)
    with pytest.raises(SystemExit):
        M._build_store(bad)
