"""Testes para DeploySettings — resolução de repos_root e de segredos (SEC-004)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from src.config import settings as S
from src.config.settings import DeploySettings, load_secret


def _settings(**kwargs) -> DeploySettings:
    base = {"github_token": "t", "github_org": "test-org"}
    base.update(kwargs)
    return DeploySettings(**base)


def test_repos_root_path_from_field(tmp_path):
    s = _settings(repos_root=str(tmp_path))
    assert s.get_repos_root_path() == tmp_path.resolve()


def test_repos_root_path_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("REPOS_ROOT", str(tmp_path))
    s = _settings(repos_root="")
    assert s.get_repos_root_path() == tmp_path.resolve()


def test_repos_root_path_from_workspace_env(tmp_path, monkeypatch):
    monkeypatch.delenv("REPOS_ROOT", raising=False)
    monkeypatch.setenv("WORKSPACE_REPOS_ROOT", str(tmp_path))
    s = _settings(repos_root="")
    assert s.get_repos_root_path() == tmp_path.resolve()


def test_repos_root_path_none_when_unset(monkeypatch):
    monkeypatch.delenv("REPOS_ROOT", raising=False)
    monkeypatch.delenv("WORKSPACE_REPOS_ROOT", raising=False)
    s = _settings(repos_root="")
    assert s.get_repos_root_path() is None


def test_defaults():
    s = _settings()
    assert s.github_org == "test-org"
    assert s.acr_registry == "d4all.azurecr.io"
    assert s.default_base_branch == "develop"
    assert isinstance(s.get_repos_root_path(), (Path, type(None)))


# ── load_secret (Vault-fallback, STD-SEC-004) ─────────────────────────────────
def test_load_secret_no_vault_returns_env(monkeypatch):
    monkeypatch.delenv("VAULT_ADDR", raising=False)
    assert load_secret("deploy-mcp/github_token", "from-env") == "from-env"


def test_load_secret_vault_import_failure_degrades(monkeypatch):
    # VAULT_ADDR setado mas platform_crypto ausente → degrada p/ o fallback de env.
    monkeypatch.setenv("VAULT_ADDR", "http://vault.local:8200")
    monkeypatch.setitem(sys.modules, "platform_crypto", None)
    assert load_secret("deploy-mcp/github_token", "fallback") == "fallback"


def test_load_secret_vault_success(monkeypatch):
    monkeypatch.setenv("VAULT_ADDR", "http://vault.local:8200")

    class _FakeVault:
        def __init__(self, addr: str) -> None:
            pass

        def get_secret(self, key: str) -> str:
            return "from-vault"

    fake_mod = type("M", (), {"VaultSecretsClient": _FakeVault})
    monkeypatch.setitem(sys.modules, "platform_crypto", fake_mod)
    assert load_secret("deploy-mcp/github_token", "fallback") == "from-vault"


def test_load_secret_vault_empty_degrades(monkeypatch):
    monkeypatch.setenv("VAULT_ADDR", "http://vault.local:8200")

    class _FakeVault:
        def __init__(self, addr: str) -> None:
            pass

        def get_secret(self, key: str) -> str:
            return ""

    fake_mod = type("M", (), {"VaultSecretsClient": _FakeVault})
    monkeypatch.setitem(sys.modules, "platform_crypto", fake_mod)
    assert load_secret("deploy-mcp/github_token", "fallback") == "fallback"


# ── Roteamento das credenciais do backend via load_secret ─────────────────────
def test_github_token_resolved_via_vault(monkeypatch):
    monkeypatch.setattr(
        S,
        "load_secret",
        lambda key, fallback: "resolved-token" if key.endswith("github_token") else fallback,
    )
    s = _settings(github_token="ignored", acr_password="sp-secret")
    assert s.github_token == "resolved-token"
    # a senha do ACR não casa a key de github → mantém o fallback de env.
    assert s.acr_password == "sp-secret"


def test_acr_password_resolved_via_vault(monkeypatch):
    monkeypatch.setattr(
        S,
        "load_secret",
        lambda key, fallback: "resolved-acr" if key.endswith("acr_password") else fallback,
    )
    s = _settings()
    assert s.acr_password == "resolved-acr"


def test_secrets_fallback_to_env_without_vault(monkeypatch):
    # Sem VAULT_ADDR o comportamento é idêntico ao anterior: vem do env/kwargs.
    monkeypatch.delenv("VAULT_ADDR", raising=False)
    s = _settings(github_token="ghp_env", acr_password="acr_env")
    assert s.github_token == "ghp_env"
    assert s.acr_password == "acr_env"


def test_acr_password_empty_becomes_none(monkeypatch):
    # acr_password opcional: load_secret vazio (nem env nem Vault) → volta a None,
    # preservando o contrato "não configurado" do campo str | None.
    monkeypatch.setattr(S, "load_secret", lambda _key, _fallback: "")
    s = _settings()
    assert s.acr_password is None


# ── DB/Admin settings (ledger dual-db, credencial-zero) ───────────────────────
def test_db_settings_defaults():
    s = _settings()
    assert s.DB_ENGINE == "mysql"
    assert s.DB_PORT == 3306
    assert s.DB_USER == "root"
    assert s.ADMIN_DB_PORT == 3306


def test_db_password_resolved_via_vault(monkeypatch):
    monkeypatch.setattr(
        S,
        "load_secret",
        lambda key, fallback: "resolved-db" if key.endswith("/db_password") else fallback,
    )
    s = _settings(DB_PASSWORD="ignored")
    assert s.DB_PASSWORD == "resolved-db"


def test_admin_db_password_resolved_via_vault(monkeypatch):
    monkeypatch.setattr(
        S,
        "load_secret",
        lambda key, fallback: "resolved-admin" if key.endswith("/admin_db_password") else fallback,
    )
    s = _settings(ADMIN_DB_PASSWORD="ignored")
    assert s.ADMIN_DB_PASSWORD == "resolved-admin"


# ── enforce_security_invariants (fail-fast no boot) ───────────────────────────
def test_enforce_ok_local():
    _settings(RUNTIME_ENV="local").enforce_security_invariants()  # não levanta


def test_enforce_docs_enabled_forbidden():
    with pytest.raises(RuntimeError, match="STD-SEC-001"):
        _settings(DOCS_ENABLED=True).enforce_security_invariants()


def test_enforce_bad_audience():
    with pytest.raises(RuntimeError, match="STD-SEC-006"):
        _settings(MCP_TWIN_AUDIENCE="deploy-mcp").enforce_security_invariants()


def test_enforce_cloud_requires_jwks():
    with pytest.raises(RuntimeError, match="URL_ADMIN_TWIN_JWKS"):
        _settings(RUNTIME_ENV="cloud", URL_ADMIN_TWIN_JWKS="").enforce_security_invariants()


def test_enforce_cloud_requires_github_token():
    with pytest.raises(RuntimeError, match="DEPLOY_GITHUB_TOKEN"):
        _settings(
            RUNTIME_ENV="cloud",
            github_token="",
            URL_ADMIN_TWIN_JWKS="http://a/jwks",
        ).enforce_security_invariants()


def test_enforce_cloud_requires_admin_db():
    with pytest.raises(RuntimeError, match="ADMIN_DB_HOST/ADMIN_DB_PASSWORD"):
        _settings(
            RUNTIME_ENV="cloud",
            github_token="ghp_x",
            URL_ADMIN_TWIN_JWKS="http://a/jwks",
            ADMIN_DB_HOST="",
            ADMIN_DB_PASSWORD="",
        ).enforce_security_invariants()
