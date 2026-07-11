"""Testes do contrato de segurança das settings (STD-SEC-001/004/006, STD-OBS-001).

Cobre: validação de RUNTIME_ENV, enforce_security_invariants (docs/audiência/cloud:
jwks + admin DB), Vault-fallback load_secret (degradação graciosa p/ env) e
configure_logging (JSON). Sem banco — puro contrato de configuração."""

from __future__ import annotations

import json
import logging

import pytest

from src.config import logging as log_mod
from src.config.settings import DevTwinSettings, load_secret


def _base(**over: object) -> DevTwinSettings:
    kw: dict[str, object] = {
        "MCP_TWIN_AUDIENCE": "mcp:dev-twin-mcp",
        "URL_ADMIN_TWIN_JWKS": "http://admin.local/jwks.json",
        "DB_HOST": "db.local",
        "DB_PASSWORD": "db-pw",
        "ADMIN_DB_HOST": "admin.local",
        "ADMIN_DB_PASSWORD": "admin-pw",
    }
    kw.update(over)
    return DevTwinSettings(**kw)


# ── RUNTIME_ENV ────────────────────────────────────────────────────────────────
def test_runtime_env_normalizes():
    assert _base(RUNTIME_ENV="CLOUD").runtime_env == "cloud"
    assert _base(RUNTIME_ENV=" local ").runtime_env == "local"


def test_runtime_env_invalid_raises():
    with pytest.raises(ValueError):
        _base(RUNTIME_ENV="staging")


# ── enforce_security_invariants ────────────────────────────────────────────────
def test_enforce_ok_local():
    _base(RUNTIME_ENV="local").enforce_security_invariants()  # não levanta


def test_enforce_docs_enabled_raises():
    with pytest.raises(RuntimeError, match="STD-SEC-001"):
        _base(DOCS_ENABLED=True).enforce_security_invariants()


def test_enforce_bad_audience_raises():
    with pytest.raises(RuntimeError, match="STD-SEC-006"):
        _base(MCP_TWIN_AUDIENCE="dev-twin-mcp").enforce_security_invariants()


def test_enforce_cloud_requires_jwks():
    s = _base(RUNTIME_ENV="cloud", URL_ADMIN_TWIN_JWKS="")
    with pytest.raises(RuntimeError, match="URL_ADMIN_TWIN_JWKS"):
        s.enforce_security_invariants()


def test_enforce_cloud_requires_admin_db_host():
    s = _base(RUNTIME_ENV="cloud", ADMIN_DB_HOST="")
    with pytest.raises(RuntimeError, match="STD-SEC-004"):
        s.enforce_security_invariants()


def test_enforce_cloud_requires_admin_db_password():
    s = _base(RUNTIME_ENV="cloud", ADMIN_DB_PASSWORD="")
    with pytest.raises(RuntimeError, match="STD-SEC-004"):
        s.enforce_security_invariants()


def test_enforce_cloud_ok_with_all_secrets():
    _base(RUNTIME_ENV="cloud").enforce_security_invariants()  # não levanta


# ── Vault-fallback load_secret ─────────────────────────────────────────────────
def test_load_secret_env_when_no_vault(monkeypatch):
    monkeypatch.delenv("VAULT_ADDR", raising=False)
    assert load_secret("dev-twin-mcp/db_password", "env-pw") == "env-pw"


def test_load_secret_degrades_when_vault_import_fails(monkeypatch):
    # VAULT_ADDR setado mas platform_crypto ausente → degrada p/ env, sem quebrar.
    monkeypatch.setenv("VAULT_ADDR", "https://vault.local")
    assert load_secret("dev-twin-mcp/db_password", "env-pw") == "env-pw"


# ── configure_logging (STD-OBS-001) ────────────────────────────────────────────
def test_configure_logging_emits_json(capsys):
    log_mod.configure_logging(_base(MCP_SERVICE_LOG_LEVEL="INFO"))
    logging.getLogger("t").info("hello", extra={"tenant_id": "T-1"})
    err = capsys.readouterr().err.strip().splitlines()[-1]
    payload = json.loads(err)
    assert payload["service"] == "dev-twin-mcp"
    assert payload["msg"] == "hello"
    assert payload["tenant_id"] == "T-1"
