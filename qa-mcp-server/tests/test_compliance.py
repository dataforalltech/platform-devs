"""Testes do padrão Tier-2 de compliance (STD-SEC-001/004/006, STD-OBS-001).

Cobre:
  - QASettings.runtime_env / _validate_runtime_env
  - QASettings.enforce_security_invariants (todas as invariantes, local e cloud)
  - config.secrets.load_secret (env, default, Vault ok, Vault indisponível)
  - config.logging.JsonLogFormatter / configure_logging
"""

from __future__ import annotations

import json
import logging

import pytest

from src.config import secrets as S
from src.config.logging import JsonLogFormatter, configure_logging
from src.config.settings import NAMESPACE, QASettings


# ── runtime_env ───────────────────────────────────────────────────────────────
def test_runtime_env_default_is_local():
    assert QASettings().runtime_env == "local"


def test_runtime_env_normalizes_and_lowercases():
    assert QASettings(runtime_env="  CLOUD ").runtime_env == "cloud"


def test_runtime_env_invalid_raises():
    with pytest.raises(ValueError):
        QASettings(runtime_env="staging")


# ── enforce_security_invariants ───────────────────────────────────────────────
def _cloud(**over) -> QASettings:
    base = dict(
        runtime_env="cloud",
        mcp_twin_audience="mcp:qa-mcp",
        url_admin_twin_jwks="http://admin.local/jwks.json",
        pg_dsn="postgresql://u:p@db:5432/qa",
        docs_enabled=False,
    )
    base.update(over)
    return QASettings(**base)


def test_enforce_ok_local_minimal():
    # local: jwks e pg_dsn NÃO são exigidos.
    QASettings(mcp_twin_audience="mcp:qa-mcp", docs_enabled=False).enforce_security_invariants()


def test_enforce_ok_cloud_full():
    _cloud().enforce_security_invariants()  # não levanta


def test_enforce_rejects_docs_enabled():
    with pytest.raises(RuntimeError, match="STD-SEC-001"):
        QASettings(docs_enabled=True).enforce_security_invariants()


def test_enforce_rejects_bad_audience():
    with pytest.raises(RuntimeError, match="STD-SEC-006"):
        QASettings(mcp_twin_audience="qa-mcp").enforce_security_invariants()


def test_enforce_cloud_requires_jwks():
    with pytest.raises(RuntimeError, match="URL_ADMIN_TWIN_JWKS"):
        _cloud(url_admin_twin_jwks="").enforce_security_invariants()


def test_enforce_cloud_requires_pg_dsn():
    with pytest.raises(RuntimeError, match="PG_DSN"):
        _cloud(pg_dsn="").enforce_security_invariants()


# ── load_secret ───────────────────────────────────────────────────────────────
def test_load_secret_from_env(monkeypatch):
    monkeypatch.delenv("VAULT_ADDR", raising=False)
    monkeypatch.setenv("PG_DSN", "postgresql://u:p@h/d")
    assert S.load_secret("qa/pg", env_var="PG_DSN") == "postgresql://u:p@h/d"


def test_load_secret_default_when_absent(monkeypatch):
    monkeypatch.delenv("VAULT_ADDR", raising=False)
    monkeypatch.delenv("PG_DSN", raising=False)
    assert S.load_secret("qa/pg", env_var="PG_DSN", default="fallback") == "fallback"


def test_load_secret_prefers_vault(monkeypatch):
    monkeypatch.setenv("VAULT_ADDR", "http://vault:8200")
    monkeypatch.setenv("PG_DSN", "env-dsn")

    class _Client:
        def get_secret(self, name):
            return "vault-dsn"

    fake_mod = type(S)("platform_crypto")
    fake_mod.VaultSecretsClient = lambda *a, **k: _Client()
    monkeypatch.setitem(__import__("sys").modules, "platform_crypto", fake_mod)
    assert S.load_secret("qa/pg", env_var="PG_DSN") == "vault-dsn"


def test_load_secret_vault_unavailable_falls_back_to_env(monkeypatch):
    # VAULT_ADDR setado mas platform_crypto indisponível → cai para env (boot não quebra).
    monkeypatch.setenv("VAULT_ADDR", "http://vault:8200")
    monkeypatch.setenv("PG_DSN", "env-dsn")
    monkeypatch.setitem(__import__("sys").modules, "platform_crypto", None)
    assert S.load_secret("qa/pg", env_var="PG_DSN") == "env-dsn"


def test_load_secret_vault_empty_falls_back_to_env(monkeypatch):
    monkeypatch.setenv("VAULT_ADDR", "http://vault:8200")
    monkeypatch.setenv("PG_DSN", "env-dsn")

    class _Client:
        def get_secret(self, name):
            return ""

    fake_mod = type(S)("platform_crypto")
    fake_mod.VaultSecretsClient = lambda *a, **k: _Client()
    monkeypatch.setitem(__import__("sys").modules, "platform_crypto", fake_mod)
    assert S.load_secret("qa/pg", env_var="PG_DSN") == "env-dsn"


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
