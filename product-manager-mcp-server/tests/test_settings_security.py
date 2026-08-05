"""Contrato de segurança das settings (STD-SEC-001/004/006) + conformidade com os
protocolos DBSettings/AdminDBSettings do ORM (dual-db, credencial-zero)."""

from __future__ import annotations

import pytest
from platform_database.settings import AdminDBSettings, DBSettings

from src.config import settings as S
from src.config.settings import load_secret, NAMESPACE, ProductManagerSettings, SecretResolutionError


def _base(**over: object) -> ProductManagerSettings:
    kw: dict[str, object] = {
        "MCP_TWIN_AUDIENCE": "mcp:product-manager-mcp",
        "URL_ADMIN_TWIN_JWKS": "http://admin.local/jwks.json",
        "ADMIN_DB_HOST": "admin-mysql",
        "ADMIN_DB_PASSWORD": "pw",
    }
    kw.update(over)
    return ProductManagerSettings(**kw)



def _vault_duplo(monkeypatch, **valores: str) -> None:
    """Instala um Vault de mentira com a API REAL da lib (``service=`` / ``get()``).

    Necessário em qualquer teste que construa Settings com ``RUNTIME_ENV="cloud"``:
    ali o bootstrap resolve do Vault e NÃO aceita fallback de env (STD-SEC-002
    §MUST — falha fechada). Sem o dublê, a própria construção recusa.
    """

    class _FakeVault:
        def __init__(self, service: str) -> None:
            pass

        def get(self, name: str, *, field: str = "value") -> str:
            return valores.get(name, "")

    monkeypatch.setitem(
        __import__("sys").modules,
        "platform_crypto",
        type("M", (), {"VaultSecretsClient": _FakeVault}),
    )

# ── RUNTIME_ENV ───────────────────────────────────────────────────────────────
def test_runtime_env_normalizes(monkeypatch):
    _vault_duplo(monkeypatch, db_password="pw", admin_db_password="pw")
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
    ProductManagerSettings().enforce_security_invariants()  # local não exige JWKS/admin


def test_enforce_docs_enabled_raises():
    with pytest.raises(RuntimeError, match="STD-SEC-001"):
        _base(DOCS_ENABLED=True).enforce_security_invariants()


def test_enforce_bad_audience_raises():
    with pytest.raises(RuntimeError, match="STD-SEC-006"):
        _base(MCP_TWIN_AUDIENCE="product-manager-mcp").enforce_security_invariants()


def test_enforce_cloud_requires_jwks(monkeypatch):
    _vault_duplo(monkeypatch, db_password="pw", admin_db_password="pw")
    with pytest.raises(RuntimeError, match="URL_ADMIN_TWIN_JWKS"):
        _base(RUNTIME_ENV="cloud", URL_ADMIN_TWIN_JWKS="").enforce_security_invariants()


def test_enforce_cloud_requires_admin_db(monkeypatch):
    # Em cloud a fonte da senha é o Vault, não o env que `_base` passa: para
    # o invariante disparar, quem tem de estar sem o segredo é o Vault.
    _vault_duplo(monkeypatch, db_password="pw")
    with pytest.raises(RuntimeError, match="STD-SEC-004"):
        _base(RUNTIME_ENV="cloud", ADMIN_DB_PASSWORD="").enforce_security_invariants()
    _vault_duplo(monkeypatch, db_password="pw", admin_db_password="pw")
    with pytest.raises(RuntimeError, match="STD-SEC-004"):
        _base(RUNTIME_ENV="cloud", ADMIN_DB_HOST="").enforce_security_invariants()


def test_enforce_cloud_ok_with_all(monkeypatch):
    _vault_duplo(monkeypatch, db_password="pw", admin_db_password="pw")
    _base(RUNTIME_ENV="cloud").enforce_security_invariants()


# ── load_secret (Vault-fallback) ──────────────────────────────────────────────
def test_load_secret_no_vault_returns_env(monkeypatch):
    monkeypatch.delenv("VAULT_ADDR", raising=False)
    assert load_secret("db_password", "from-env") == "from-env"


def test_load_secret_vault_import_failure_degrades(monkeypatch):
    monkeypatch.setenv("VAULT_ADDR", "http://vault.local:8200")
    assert load_secret("db_password", "fallback") == "fallback"


def test_load_secret_vault_success(monkeypatch):
    monkeypatch.setenv("VAULT_ADDR", "http://vault.local:8200")

    class _FakeVault:
        def __init__(self, service: str) -> None:
            pass

        def get(self, name: str, *, field: str = "value") -> str:
            return "from-vault"

    fake_mod = type("M", (), {"VaultSecretsClient": _FakeVault})
    monkeypatch.setitem(__import__("sys").modules, "platform_crypto", fake_mod)
    assert load_secret("db_password", "fallback") == "from-vault"


def test_load_secret_vault_empty_degrades(monkeypatch):
    monkeypatch.setenv("VAULT_ADDR", "http://vault.local:8200")

    class _FakeVault:
        def __init__(self, service: str) -> None:
            pass

        def get(self, name: str, *, field: str = "value") -> str:
            return ""

    fake_mod = type("M", (), {"VaultSecretsClient": _FakeVault})
    monkeypatch.setitem(__import__("sys").modules, "platform_crypto", fake_mod)
    assert load_secret("db_password", "fallback") == "fallback"


def test_settings_resolves_secrets_via_vault(monkeypatch):
    monkeypatch.setattr(S, "load_secret", lambda _key, fallback, **_kw: "resolved-pw")
    s = ProductManagerSettings(DB_PASSWORD="ignored", ADMIN_DB_PASSWORD="ignored")
    assert s.DB_PASSWORD == "resolved-pw"
    assert s.ADMIN_DB_PASSWORD == "resolved-pw"


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
