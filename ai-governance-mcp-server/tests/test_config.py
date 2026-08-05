"""Config: RUNTIME_ENV, enforce_security_invariants (STD-SEC-001/004/006),
conformidade com os protocolos DBSettings/AdminDBSettings do ORM (dual-db,
credencial-zero), load_secret (Vault-fallback) e o logging estruturado JSON
(STD-OBS-001).

Estes travam o contrato de compliance Tier-2: docs sempre off, audiência do inner
token no formato mcp:<namespace>, JWKS + conexão admin obrigatórios em cloud, e uma
linha JSON por log record com identidade do serviço + campos de correlação.
"""

from __future__ import annotations

import json
import logging

import pytest
from platform_database.settings import AdminDBSettings, DBSettings

from src.config import settings as S
from src.config.logging import JsonLogFormatter, configure_logging
from src.config.settings import load_secret, NAMESPACE, SecretResolutionError, Settings


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



def _settings(**overrides) -> Settings:
    base = {
        "MCP_TWIN_AUDIENCE": f"mcp:{NAMESPACE}",
        "URL_ADMIN_TWIN_JWKS": "http://admin.local/jwks.json",
        "ADMIN_DB_HOST": "admin-mysql",
        "ADMIN_DB_PASSWORD": "pw",
        "DOCS_ENABLED": False,
        "RUNTIME_ENV": "local",
    }
    base.update(overrides)
    return Settings(**base)


# ── RUNTIME_ENV ───────────────────────────────────────────────────────────────
def test_runtime_env_normalizes_and_defaults(monkeypatch):
    _vault_duplo(monkeypatch, db_password="pw", admin_db_password="pw")
    assert _settings(RUNTIME_ENV="  Cloud ").runtime_env == "cloud"
    assert _settings(RUNTIME_ENV="LOCAL").runtime_env == "local"


def test_runtime_env_rejects_unknown():
    with pytest.raises(ValueError):
        _settings(RUNTIME_ENV="staging")


# ── Conformidade com os protocolos do ORM (dual-db) ───────────────────────────
def test_satisfies_orm_protocols():
    s = _settings()
    assert isinstance(s, DBSettings)
    assert isinstance(s, AdminDBSettings)
    assert s.DB_ENGINE == "mysql"  # dual-db: engine default


# ── enforce_security_invariants ───────────────────────────────────────────────
def test_enforce_ok_local():
    # Não levanta: docs off, aud mcp:, local dispensa JWKS/admin.
    _settings().enforce_security_invariants()


def test_enforce_ok_cloud_with_all(monkeypatch):
    _vault_duplo(monkeypatch, db_password="pw", admin_db_password="pw")
    _settings(RUNTIME_ENV="cloud").enforce_security_invariants()


def test_enforce_blocks_docs_enabled():
    with pytest.raises(RuntimeError, match="STD-SEC-001"):
        _settings(DOCS_ENABLED=True).enforce_security_invariants()


def test_enforce_blocks_bad_audience():
    with pytest.raises(RuntimeError, match="STD-SEC-006"):
        _settings(MCP_TWIN_AUDIENCE="architecture-mcp").enforce_security_invariants()


def test_enforce_cloud_requires_jwks(monkeypatch):
    _vault_duplo(monkeypatch, db_password="pw", admin_db_password="pw")
    with pytest.raises(RuntimeError, match="URL_ADMIN_TWIN_JWKS"):
        _settings(RUNTIME_ENV="cloud", URL_ADMIN_TWIN_JWKS="").enforce_security_invariants()


def test_enforce_cloud_requires_admin_db(monkeypatch):
    _vault_duplo(monkeypatch, db_password="pw")
    with pytest.raises(RuntimeError, match="STD-SEC-004"):
        _settings(RUNTIME_ENV="cloud", ADMIN_DB_PASSWORD="").enforce_security_invariants()
    with pytest.raises(RuntimeError, match="STD-SEC-004"):
        _settings(RUNTIME_ENV="cloud", ADMIN_DB_HOST="").enforce_security_invariants()


# ── load_secret (Vault-fallback) ──────────────────────────────────────────────
def test_load_secret_no_vault_returns_env(monkeypatch):
    monkeypatch.delenv("VAULT_ADDR", raising=False)
    assert load_secret(f"{NAMESPACE}/db_password", "from-env") == "from-env"


def test_load_secret_vault_import_failure_degrades(monkeypatch):
    monkeypatch.setenv("VAULT_ADDR", "http://vault.local:8200")
    assert load_secret(f"{NAMESPACE}/db_password", "fallback") == "fallback"


def test_load_secret_vault_success(monkeypatch):
    monkeypatch.setenv("VAULT_ADDR", "http://vault.local:8200")

    class _FakeVault:
        def __init__(self, service: str) -> None:
            pass

        def get(self, name: str, *, field: str = "value") -> str:
            return "from-vault"

    fake_mod = type("M", (), {"VaultSecretsClient": _FakeVault})
    monkeypatch.setitem(__import__("sys").modules, "platform_crypto", fake_mod)
    assert load_secret(f"{NAMESPACE}/db_password", "fallback") == "from-vault"


def test_settings_resolves_secrets_via_vault(monkeypatch):
    monkeypatch.setattr(S, "load_secret", lambda _key, fallback, **_kw: "resolved-pw")
    s = Settings(DB_PASSWORD="ignored", ADMIN_DB_PASSWORD="ignored")
    assert s.DB_PASSWORD == "resolved-pw"
    assert s.ADMIN_DB_PASSWORD == "resolved-pw"


# ── JsonLogFormatter ──────────────────────────────────────────────────────────
def test_formatter_emits_json_with_service_identity():
    rec = logging.LogRecord("x", logging.INFO, __file__, 1, "hello", None, None)
    payload = json.loads(JsonLogFormatter().format(rec))
    assert payload["service"] == NAMESPACE
    assert payload["level"] == "INFO"
    assert payload["msg"] == "hello"


def test_formatter_includes_correlation_fields():
    rec = logging.LogRecord("x", logging.INFO, __file__, 1, "m", None, None)
    rec.tenant_id = "T-1"
    rec.tool = "get_port_map"
    payload = json.loads(JsonLogFormatter().format(rec))
    assert payload["tenant_id"] == "T-1"
    assert payload["tool"] == "get_port_map"


def test_formatter_renders_exception_type():
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        rec = logging.LogRecord("x", logging.ERROR, __file__, 1, "err", None, sys.exc_info())
    payload = json.loads(JsonLogFormatter().format(rec))
    assert payload["exc_type"] == "ValueError"
    assert "boom" in payload["exc"]


# ── configure_logging ─────────────────────────────────────────────────────────
def test_configure_logging_installs_single_json_handler():
    root = logging.getLogger()
    original = root.handlers[:]
    original_level = root.level
    try:
        configure_logging(_settings(log_level="WARNING"))
        assert len(root.handlers) == 1
        assert isinstance(root.handlers[0].formatter, JsonLogFormatter)
        assert root.level == logging.WARNING
        # idempotente: não acumula handlers
        configure_logging(_settings())
        assert len(logging.getLogger().handlers) == 1
    finally:
        root.handlers[:] = original
        root.setLevel(original_level)


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
