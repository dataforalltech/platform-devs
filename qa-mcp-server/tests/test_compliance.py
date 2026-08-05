"""Testes do padrão Tier-2 de compliance (STD-SEC-001/004/006, STD-OBS-001) +
conformidade com os protocolos DBSettings/AdminDBSettings do ORM (dual-db, credencial-zero).

Cobre:
  - QASettings.runtime_env / _validate_runtime_env
  - QASettings satisfaz DBSettings/AdminDBSettings (isinstance runtime_checkable)
  - QASettings.enforce_security_invariants (todas as invariantes, local e cloud)
  - QASettings._resolve_secrets (senhas via load_secret)
  - config.secrets.load_secret (env, default, Vault ok, Vault indisponível, Vault vazio)
  - config.logging.JsonLogFormatter / configure_logging
"""

from __future__ import annotations

import json
import logging

import pytest
from platform_database.settings import AdminDBSettings, DBSettings

from src.config import secrets as S
from src.config import settings as SET
from src.config.logging import JsonLogFormatter, configure_logging
from src.config.settings import NAMESPACE, QASettings


def _vault_duplo(monkeypatch, **valores: str) -> dict[str, str]:
    """Instala um Vault de mentira com a API REAL da lib (``service=`` / ``get()``).

    Necessário em qualquer teste que construa Settings com ``runtime_env="cloud"``:
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


# ── runtime_env ───────────────────────────────────────────────────────────────
def test_runtime_env_default_is_local():
    assert QASettings().runtime_env == "local"


def test_runtime_env_normalizes_and_lowercases(monkeypatch):
    _vault_duplo(monkeypatch, db_password="pw", admin_db_password="pw")
    assert QASettings(runtime_env="  CLOUD ").runtime_env == "cloud"


def test_runtime_env_invalid_raises():
    with pytest.raises(ValueError):
        QASettings(runtime_env="staging")


# ── Conformidade com os protocolos do ORM ─────────────────────────────────────
def test_satisfies_orm_protocols():
    s = QASettings(mcp_twin_audience="mcp:qa-mcp")
    assert isinstance(s, DBSettings)
    assert isinstance(s, AdminDBSettings)
    assert s.DB_ENGINE == "mysql"  # dual-db: engine default


# ── enforce_security_invariants ───────────────────────────────────────────────
def _cloud(**over) -> QASettings:
    base = dict(
        runtime_env="cloud",
        mcp_twin_audience="mcp:qa-mcp",
        url_admin_twin_jwks="http://admin.local/jwks.json",
        ADMIN_DB_HOST="admin-mysql",
        ADMIN_DB_PASSWORD="pw",
        docs_enabled=False,
    )
    base.update(over)
    return QASettings(**base)


def test_enforce_ok_local_minimal():
    # local: jwks e admin-db NÃO são exigidos.
    QASettings(mcp_twin_audience="mcp:qa-mcp", docs_enabled=False).enforce_security_invariants()


def test_enforce_ok_cloud_full(monkeypatch):
    _vault_duplo(monkeypatch, db_password="pw", admin_db_password="pw")
    _cloud().enforce_security_invariants()  # não levanta


def test_enforce_rejects_docs_enabled():
    with pytest.raises(RuntimeError, match="STD-SEC-001"):
        QASettings(docs_enabled=True).enforce_security_invariants()


def test_enforce_rejects_bad_audience():
    with pytest.raises(RuntimeError, match="STD-SEC-006"):
        QASettings(mcp_twin_audience="qa-mcp").enforce_security_invariants()


def test_enforce_cloud_requires_jwks(monkeypatch):
    _vault_duplo(monkeypatch, db_password="pw", admin_db_password="pw")
    with pytest.raises(RuntimeError, match="URL_ADMIN_TWIN_JWKS"):
        _cloud(url_admin_twin_jwks="").enforce_security_invariants()


def test_enforce_cloud_requires_admin_db(monkeypatch):
    # Em cloud a fonte da senha é o Vault, não o env: para o invariante disparar,
    # quem tem de estar sem o segredo é o Vault. Limpar o env já não basta.
    monkeypatch.delenv("ADMIN_DB_PASSWORD", raising=False)
    monkeypatch.delenv("ADMIN_DB_HOST", raising=False)
    _vault_duplo(monkeypatch, db_password="pw")
    with pytest.raises(RuntimeError, match="STD-SEC-004"):
        _cloud(ADMIN_DB_PASSWORD="").enforce_security_invariants()
    _vault_duplo(monkeypatch, db_password="pw", admin_db_password="pw")
    with pytest.raises(RuntimeError, match="STD-SEC-004"):
        _cloud(ADMIN_DB_HOST="").enforce_security_invariants()


# ── _resolve_secrets (senhas via load_secret) ─────────────────────────────────
def test_settings_resolves_secrets_via_load_secret(monkeypatch):
    def _fake(_name, *, env_var, default="", **_kw):
        return "resolved-pw"

    monkeypatch.setattr(SET, "load_secret", _fake)
    s = QASettings(DB_PASSWORD="ignored", ADMIN_DB_PASSWORD="ignored")
    assert s.DB_PASSWORD == "resolved-pw"
    assert s.ADMIN_DB_PASSWORD == "resolved-pw"


# ── load_secret ───────────────────────────────────────────────────────────────
def test_load_secret_from_env(monkeypatch):
    monkeypatch.delenv("VAULT_ADDR", raising=False)
    monkeypatch.setenv("DB_PASSWORD", "pw-from-env")
    assert S.load_secret("db_password", env_var="DB_PASSWORD") == "pw-from-env"


def test_load_secret_default_when_absent(monkeypatch):
    monkeypatch.delenv("VAULT_ADDR", raising=False)
    monkeypatch.delenv("DB_PASSWORD", raising=False)
    assert S.load_secret("db_password", env_var="DB_PASSWORD", default="fallback") == "fallback"


def test_load_secret_prefers_vault(monkeypatch):
    monkeypatch.setenv("VAULT_ADDR", "http://vault:8200")
    monkeypatch.setenv("DB_PASSWORD", "env-pw")
    visto = _vault_duplo(monkeypatch, db_password="vault-pw")
    assert S.load_secret("db_password", env_var="DB_PASSWORD") == "vault-pw"
    # Regressão: o 1º argumento do cliente é o ESPAÇO do serviço, nunca a URL do
    # Vault — o bug original era `VaultSecretsClient().get_secret(name)`, que nem
    # sequer satisfazia a assinatura da lib.
    assert visto["service"] == S.SERVICE
    assert visto["name"] == "db_password"


# ── falha fechada em cloud (STD-SEC-002 §MUST) ────────────────────────────────
def test_load_secret_cloud_vault_indisponivel_recusa(monkeypatch):
    monkeypatch.setenv("VAULT_ADDR", "http://vault:8200")
    monkeypatch.setenv("DB_PASSWORD", "env-pw")

    class _Quebrado:
        def __init__(self, service: str) -> None:
            pass

        def get(self, name: str, *, field: str = "value") -> str:
            raise RuntimeError("vault down")

    monkeypatch.setitem(
        __import__("sys").modules,
        "platform_crypto",
        type("m", (), {"VaultSecretsClient": _Quebrado}),
    )
    with pytest.raises(S.SecretResolutionError):
        S.load_secret("db_password", env_var="DB_PASSWORD", runtime_env="cloud")


def test_load_secret_cloud_ignora_fallback_de_env(monkeypatch):
    monkeypatch.setenv("VAULT_ADDR", "http://vault:8200")
    monkeypatch.setenv("DB_PASSWORD", "env-pw")
    _vault_duplo(monkeypatch)
    assert S.load_secret("db_password", env_var="DB_PASSWORD", runtime_env="cloud") == ""


def test_load_secret_vault_unavailable_falls_back_to_env(monkeypatch):
    # VAULT_ADDR setado mas platform_crypto indisponível → cai para env (boot não quebra).
    monkeypatch.setenv("VAULT_ADDR", "http://vault:8200")
    monkeypatch.setenv("DB_PASSWORD", "env-pw")
    monkeypatch.setitem(__import__("sys").modules, "platform_crypto", None)
    assert S.load_secret("qa-mcp/db_password", env_var="DB_PASSWORD") == "env-pw"


def test_load_secret_vault_empty_falls_back_to_env(monkeypatch):
    monkeypatch.setenv("VAULT_ADDR", "http://vault:8200")
    monkeypatch.setenv("DB_PASSWORD", "env-pw")

    class _Client:
        def get_secret(self, name):
            return ""

    fake_mod = type(S)("platform_crypto")
    fake_mod.VaultSecretsClient = lambda *a, **k: _Client()
    monkeypatch.setitem(__import__("sys").modules, "platform_crypto", fake_mod)
    assert S.load_secret("qa-mcp/db_password", env_var="DB_PASSWORD") == "env-pw"


# ── logging estruturado ───────────────────────────────────────────────────────
def test_json_formatter_basic():
    rec = logging.LogRecord("l", logging.INFO, __file__, 1, "hello", None, None)
    out = json.loads(JsonLogFormatter().format(rec))
    assert out["service"] == NAMESPACE
    assert out["level"] == "INFO"
    assert out["msg"] == "hello"


def test_json_formatter_correlation_and_exc():
    rec = logging.LogRecord("l", logging.ERROR, __file__, 1, "boom", None, None)
    rec.tenant_id = "T-1"
    try:
        raise ValueError("x")
    except ValueError:
        import sys

        rec.exc_info = sys.exc_info()
    out = json.loads(JsonLogFormatter().format(rec))
    assert out["tenant_id"] == "T-1"
    assert out["exc_type"] == "ValueError"


def test_configure_logging_installs_json_handler():
    configure_logging(QASettings(log_level="DEBUG"))
    root = logging.getLogger()
    assert len(root.handlers) == 1
    assert isinstance(root.handlers[0].formatter, JsonLogFormatter)
    assert root.level == logging.DEBUG
