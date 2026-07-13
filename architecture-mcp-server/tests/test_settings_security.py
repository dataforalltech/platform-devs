"""Contrato de segurança das settings (STD-SEC-001/004/006) + conformidade com os
protocolos DBSettings/AdminDBSettings do ORM (dual-db, credencial-zero)."""

from __future__ import annotations

import pytest
from platform_database.settings import AdminDBSettings, DBSettings

from src.config import settings as S
from src.config.settings import ArchitectureSettings, load_secret


def _base(**over: object) -> ArchitectureSettings:
    kw: dict[str, object] = {
        "MCP_TWIN_AUDIENCE": "mcp:architecture-mcp",
        "URL_ADMIN_TWIN_JWKS": "http://admin.local/jwks.json",
        "ADMIN_DB_HOST": "admin-mysql",
        "ADMIN_DB_PASSWORD": "pw",
    }
    kw.update(over)
    return ArchitectureSettings(**kw)


# ── RUNTIME_ENV ───────────────────────────────────────────────────────────────
def test_runtime_env_normalizes():
    assert _base(RUNTIME_ENV="CLOUD").runtime_env == "cloud"
    assert _base(RUNTIME_ENV=" Local ").runtime_env == "local"


def test_runtime_env_rejects_unknown():
    with pytest.raises(ValueError):
        _base(RUNTIME_ENV="staging")


# ── Conformidade com os protocolos do ORM ─────────────────────────────────────
def test_satisfies_orm_protocols():
    s = _base()
    assert isinstance(s, DBSettings)
    assert isinstance(s, AdminDBSettings)
    assert s.DB_ENGINE == "mysql"  # dual-db: engine default


# ── enforce_security_invariants ───────────────────────────────────────────────
def test_enforce_ok_local_defaults():
    ArchitectureSettings().enforce_security_invariants()  # local não exige JWKS/admin


def test_enforce_docs_enabled_raises():
    with pytest.raises(RuntimeError, match="STD-SEC-001"):
        _base(DOCS_ENABLED=True).enforce_security_invariants()


def test_enforce_bad_audience_raises():
    with pytest.raises(RuntimeError, match="STD-SEC-006"):
        _base(MCP_TWIN_AUDIENCE="architecture-mcp").enforce_security_invariants()


def test_enforce_cloud_requires_jwks():
    with pytest.raises(RuntimeError, match="URL_ADMIN_TWIN_JWKS"):
        _base(RUNTIME_ENV="cloud", URL_ADMIN_TWIN_JWKS="").enforce_security_invariants()


def test_enforce_cloud_requires_admin_db():
    with pytest.raises(RuntimeError, match="STD-SEC-004"):
        _base(RUNTIME_ENV="cloud", ADMIN_DB_PASSWORD="").enforce_security_invariants()
    with pytest.raises(RuntimeError, match="STD-SEC-004"):
        _base(RUNTIME_ENV="cloud", ADMIN_DB_HOST="").enforce_security_invariants()


def test_enforce_cloud_ok_with_all():
    _base(RUNTIME_ENV="cloud").enforce_security_invariants()


# ── load_secret (Vault-fallback) ──────────────────────────────────────────────
def test_load_secret_no_vault_returns_env(monkeypatch):
    monkeypatch.delenv("VAULT_ADDR", raising=False)
    assert load_secret("architecture-mcp/db_password", "from-env") == "from-env"


def test_load_secret_vault_import_failure_degrades(monkeypatch):
    monkeypatch.setenv("VAULT_ADDR", "http://vault.local:8200")
    assert load_secret("architecture-mcp/db_password", "fallback") == "fallback"


def test_load_secret_vault_success(monkeypatch):
    monkeypatch.setenv("VAULT_ADDR", "http://vault.local:8200")

    class _FakeVault:
        def __init__(self, addr: str) -> None:
            pass

        def get_secret(self, key: str) -> str:
            return "from-vault"

    fake_mod = type("M", (), {"VaultSecretsClient": _FakeVault})
    monkeypatch.setitem(__import__("sys").modules, "platform_crypto", fake_mod)
    assert load_secret("architecture-mcp/db_password", "fallback") == "from-vault"


def test_load_secret_vault_empty_degrades(monkeypatch):
    monkeypatch.setenv("VAULT_ADDR", "http://vault.local:8200")

    class _FakeVault:
        def __init__(self, addr: str) -> None:
            pass

        def get_secret(self, key: str) -> str:
            return ""

    fake_mod = type("M", (), {"VaultSecretsClient": _FakeVault})
    monkeypatch.setitem(__import__("sys").modules, "platform_crypto", fake_mod)
    assert load_secret("architecture-mcp/db_password", "fallback") == "fallback"


def test_settings_resolves_secrets_via_vault(monkeypatch):
    monkeypatch.setattr(S, "load_secret", lambda _key, fallback: "resolved-pw")
    s = ArchitectureSettings(DB_PASSWORD="ignored", ADMIN_DB_PASSWORD="ignored")
    assert s.DB_PASSWORD == "resolved-pw"
    assert s.ADMIN_DB_PASSWORD == "resolved-pw"
