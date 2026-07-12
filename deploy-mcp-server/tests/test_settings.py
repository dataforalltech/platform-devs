"""Testes para DeploySettings — resolução de repos_root e de segredos (SEC-004)."""

from __future__ import annotations

import sys
from pathlib import Path

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
