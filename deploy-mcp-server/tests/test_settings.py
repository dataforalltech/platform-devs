"""Testes para DeploySettings — resolução de repos_root e de segredos (SEC-004)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from src.config import settings as S
from src.config.settings import DeploySettings, load_secret, NAMESPACE, SecretResolutionError


def _vault_duplo(monkeypatch, **valores: str) -> dict[str, str]:
    """Instala um Vault de mentira com a API REAL da lib (``service=`` / ``get()``).

    Necessário em qualquer teste que construa Settings com ``RUNTIME_ENV="cloud"``:
    ali o bootstrap resolve do Vault e NÃO aceita fallback de env (STD-SEC-002
    §MUST — falha fechada). Sem o dublê, a própria construção recusa.
    """
    visto: dict[str, str] = {}

    class _FakeVault:
        def __init__(self, service: str) -> None:
            visto["service"] = service

        def get(self, name: str, *, field: str = "value") -> str:
            visto["name"] = name
            return valores.get(name, "")

    monkeypatch.setitem(
        __import__("sys").modules,
        "platform_crypto",
        type("m", (), {"VaultSecretsClient": _FakeVault}),
    )
    return visto



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
    assert load_secret("github_token", "from-env") == "from-env"


def test_load_secret_vault_import_failure_degrades(monkeypatch):
    # VAULT_ADDR setado mas platform_crypto ausente → degrada p/ o fallback de env.
    monkeypatch.setenv("VAULT_ADDR", "http://vault.local:8200")
    monkeypatch.setitem(sys.modules, "platform_crypto", None)
    assert load_secret("github_token", "fallback") == "fallback"


def test_load_secret_vault_success(monkeypatch):
    monkeypatch.setenv("VAULT_ADDR", "http://vault.local:8200")

    class _FakeVault:
        def __init__(self, service: str) -> None:
            pass

        def get(self, name: str, *, field: str = "value") -> str:
            return "from-vault"

    fake_mod = type("M", (), {"VaultSecretsClient": _FakeVault})
    monkeypatch.setitem(sys.modules, "platform_crypto", fake_mod)
    assert load_secret("github_token", "fallback") == "from-vault"


def test_load_secret_vault_empty_degrades(monkeypatch):
    monkeypatch.setenv("VAULT_ADDR", "http://vault.local:8200")

    class _FakeVault:
        def __init__(self, service: str) -> None:
            pass

        def get(self, name: str, *, field: str = "value") -> str:
            return ""

    fake_mod = type("M", (), {"VaultSecretsClient": _FakeVault})
    monkeypatch.setitem(sys.modules, "platform_crypto", fake_mod)
    assert load_secret("github_token", "fallback") == "fallback"


# ── Roteamento das credenciais do backend via load_secret ─────────────────────
def test_github_token_resolved_via_vault(monkeypatch):
    monkeypatch.setattr(
        S,
        "load_secret",
        lambda key, fallback, **_kw: "resolved-token" if key == "github_token" else fallback,
    )
    s = _settings(github_token="ignored", acr_password="sp-secret")
    assert s.github_token == "resolved-token"
    # a senha do ACR não casa a key de github → mantém o fallback de env.
    assert s.acr_password == "sp-secret"


def test_acr_password_resolved_via_vault(monkeypatch):
    monkeypatch.setattr(
        S,
        "load_secret",
        lambda key, fallback, **_kw: "resolved-acr" if key == "acr_password" else fallback,
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
    monkeypatch.setattr(S, "load_secret", lambda _key, _fallback, **_kw: "")
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
        lambda key, fallback, **_kw: "resolved-db" if key == "db_password" else fallback,
    )
    s = _settings(DB_PASSWORD="ignored")
    assert s.DB_PASSWORD == "resolved-db"


def test_admin_db_password_resolved_via_vault(monkeypatch):
    monkeypatch.setattr(
        S,
        "load_secret",
        lambda key, fallback, **_kw: "resolved-admin" if key == "admin_db_password" else fallback,
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


def test_enforce_cloud_requires_jwks(monkeypatch):
    _vault_duplo(monkeypatch, db_password="pw", admin_db_password="pw", github_token="ghp_x")
    with pytest.raises(RuntimeError, match="URL_ADMIN_TWIN_JWKS"):
        _settings(RUNTIME_ENV="cloud", URL_ADMIN_TWIN_JWKS="").enforce_security_invariants()


def test_enforce_cloud_requires_github_token(monkeypatch):
    _vault_duplo(monkeypatch, db_password="pw", admin_db_password="pw")
    with pytest.raises(RuntimeError, match="DEPLOY_GITHUB_TOKEN"):
        _settings(
            RUNTIME_ENV="cloud",
            github_token="",
            URL_ADMIN_TWIN_JWKS="http://a/jwks",
        ).enforce_security_invariants()


def test_enforce_cloud_requires_admin_db(monkeypatch):
    _vault_duplo(monkeypatch, db_password="pw", github_token="ghp_x")
    with pytest.raises(RuntimeError, match="ADMIN_DB_HOST/ADMIN_DB_PASSWORD"):
        _settings(
            RUNTIME_ENV="cloud",
            github_token="ghp_x",
            URL_ADMIN_TWIN_JWKS="http://a/jwks",
            ADMIN_DB_HOST="",
            ADMIN_DB_PASSWORD="",
        ).enforce_security_invariants()


# ── falha fechada em cloud (STD-SEC-002 §MUST) ────────────────────────────────
def _fake_vault(monkeypatch, *, valor: str | None = None, erro: Exception | None = None):
    """Instala um dublê com a API REAL da lib: __init__(service) + get(name, field)."""
    visto: dict[str, str] = {}

    class _FakeVault:
        def __init__(self, service: str) -> None:
            visto["service"] = service

        def get(self, name: str, *, field: str = "value") -> str:
            visto["name"] = name
            if erro is not None:
                raise erro
            return valor or ""

    fake_mod = type("M", (), {"VaultSecretsClient": _FakeVault})
    monkeypatch.setitem(__import__("sys").modules, "platform_crypto", fake_mod)
    return visto


def test_load_secret_usa_service_e_nao_o_endereco(monkeypatch):
    """Regressao: o 1o argumento do cliente e o ESPACO do servico, nao a URL do Vault.

    A versao anterior fazia ``VaultSecretsClient(vault_addr).get_secret(key)`` —
    metodo inexistente e 1o posicional trocado. Como o dublê tinha justamente o
    metodo errado, a suite passava enquanto producao caia sempre no except.
    """
    monkeypatch.setenv("VAULT_ADDR", "http://vault.local:8200")
    visto = _fake_vault(monkeypatch, valor="from-vault")
    assert load_secret("db_password", "fallback") == "from-vault"
    assert visto["service"] == NAMESPACE
    assert visto["name"] == "db_password"
    assert "://" not in visto["service"]


def test_load_secret_cloud_vault_indisponivel_recusa(monkeypatch):
    """Em cloud, Vault fora do ar recusa o boot — nao degrada para env."""
    monkeypatch.setenv("VAULT_ADDR", "http://vault.local:8200")
    _fake_vault(monkeypatch, erro=RuntimeError("vault down"))
    with pytest.raises(SecretResolutionError):
        load_secret("db_password", "fallback", runtime_env="cloud")


def test_load_secret_cloud_ignora_fallback_de_env(monkeypatch):
    """O valor de env nao e fonte admitida em cloud, mesmo estando presente."""
    monkeypatch.setenv("VAULT_ADDR", "http://vault.local:8200")
    _fake_vault(monkeypatch, valor="")
    assert load_secret("db_password", "from-env", runtime_env="cloud") == ""


def test_load_secret_cloud_obrigatorio_vazio_recusa(monkeypatch):
    """Segredo obrigatorio vazio no Vault recusa o boot em cloud."""
    monkeypatch.setenv("VAULT_ADDR", "http://vault.local:8200")
    _fake_vault(monkeypatch, valor="")
    with pytest.raises(SecretResolutionError):
        load_secret("db_password", "from-env", runtime_env="cloud", required=True)


def test_load_secret_local_ainda_degrada_para_env(monkeypatch):
    """Fora de cloud o fallback local controlado do STD-SEC-004 continua valendo."""
    monkeypatch.setenv("VAULT_ADDR", "http://vault.local:8200")
    _fake_vault(monkeypatch, erro=RuntimeError("vault down"))
    assert load_secret("db_password", "from-env") == "from-env"
