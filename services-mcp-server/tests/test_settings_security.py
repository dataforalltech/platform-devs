"""Testes do contrato de segurança das settings (STD-SEC-001/004/006, STD-OBS-001).

Cobre ``enforce_security_invariants`` (fail-fast de boot), o validator de
``RUNTIME_ENV``, a property ``pg_dsn`` e o Vault-fallback ``load_secret``
(degradação graciosa p/ env, sem tocar Vault real).
"""

from __future__ import annotations

import pytest

from src.config import settings as S
from src.config.settings import ServicesSettings, load_secret


def _base(**over: object) -> ServicesSettings:
    kw: dict[str, object] = {
        "MCP_TWIN_AUDIENCE": "mcp:services-mcp",
        "URL_ADMIN_TWIN_JWKS": "http://admin.local/jwks.json",
        "pg_password": "pw",
    }
    kw.update(over)
    return ServicesSettings(**kw)


# ── RUNTIME_ENV validator ─────────────────────────────────────────────────────
def test_runtime_env_normalizes():
    assert _base(RUNTIME_ENV="CLOUD").runtime_env == "cloud"
    assert _base(RUNTIME_ENV=" Local ").runtime_env == "local"


def test_runtime_env_rejects_unknown():
    with pytest.raises(ValueError):
        _base(RUNTIME_ENV="staging")


# ── enforce_security_invariants ───────────────────────────────────────────────
def test_enforce_ok_local_defaults():
    # local não exige JWKS nem senha de DB
    ServicesSettings(pg_password="").enforce_security_invariants()


def test_enforce_docs_enabled_raises():
    with pytest.raises(RuntimeError, match="STD-SEC-001"):
        _base(DOCS_ENABLED=True).enforce_security_invariants()


def test_enforce_bad_audience_raises():
    with pytest.raises(RuntimeError, match="STD-SEC-006"):
        _base(MCP_TWIN_AUDIENCE="services-mcp").enforce_security_invariants()


def test_enforce_cloud_requires_jwks():
    with pytest.raises(RuntimeError, match="URL_ADMIN_TWIN_JWKS"):
        _base(RUNTIME_ENV="cloud", URL_ADMIN_TWIN_JWKS="").enforce_security_invariants()


def test_enforce_cloud_requires_db_password():
    with pytest.raises(RuntimeError, match="STD-SEC-004"):
        _base(RUNTIME_ENV="cloud", pg_password="").enforce_security_invariants()


def test_enforce_cloud_ok_with_all():
    _base(RUNTIME_ENV="cloud").enforce_security_invariants()


# ── pg_dsn (keyword libpq) ────────────────────────────────────────────────────
def test_pg_dsn_keyword_form():
    dsn = _base(pg_host="db", pg_port=5433, pg_db="svc", pg_user="u", pg_password="pw").pg_dsn
    assert "host=db" in dsn
    assert "port=5433" in dsn
    assert "dbname=svc" in dsn
    assert "user=u" in dsn
    assert "password=pw" in dsn


# ── load_secret (Vault-fallback) ──────────────────────────────────────────────
def test_load_secret_no_vault_returns_env(monkeypatch):
    monkeypatch.delenv("VAULT_ADDR", raising=False)
    assert load_secret("services-mcp/pg_password", "from-env") == "from-env"


def test_load_secret_vault_import_failure_degrades(monkeypatch):
    # VAULT_ADDR setado, mas platform_crypto ausente → degrada p/ env (boot não quebra).
    monkeypatch.setenv("VAULT_ADDR", "http://vault.local:8200")
    assert load_secret("services-mcp/pg_password", "fallback") == "fallback"


def test_load_secret_vault_success(monkeypatch):
    monkeypatch.setenv("VAULT_ADDR", "http://vault.local:8200")

    class _FakeVault:
        def __init__(self, addr: str) -> None:
            self.addr = addr

        def get_secret(self, key: str) -> str:
            return "from-vault"

    fake_mod = type("M", (), {"VaultSecretsClient": _FakeVault})
    monkeypatch.setitem(__import__("sys").modules, "platform_crypto", fake_mod)
    assert load_secret("services-mcp/pg_password", "fallback") == "from-vault"


def test_load_secret_vault_empty_degrades(monkeypatch):
    monkeypatch.setenv("VAULT_ADDR", "http://vault.local:8200")

    class _FakeVault:
        def __init__(self, addr: str) -> None:
            pass

        def get_secret(self, key: str) -> str:
            return ""

    fake_mod = type("M", (), {"VaultSecretsClient": _FakeVault})
    monkeypatch.setitem(__import__("sys").modules, "platform_crypto", fake_mod)
    assert load_secret("services-mcp/pg_password", "fallback") == "fallback"


# ── resolução da senha via model_validator usa load_secret ────────────────────
def test_settings_resolves_pg_password_via_vault(monkeypatch):
    monkeypatch.setattr(S, "load_secret", lambda _key, fallback: "resolved-pw")
    assert ServicesSettings(pg_password="ignored").pg_password == "resolved-pw"
