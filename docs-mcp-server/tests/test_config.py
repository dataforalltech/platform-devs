"""Testes de config: RUNTIME_ENV, enforce_security_invariants (STD-SEC-001/004/006),
conformidade com os protocolos DBSettings/AdminDBSettings do ORM (dual-db,
credencial-zero), o Vault-fallback de segredos e o logging estruturado JSON (STD-OBS-001).

Estes travam o contrato de compliance Tier-2: docs sempre off, audiência do inner
token no formato mcp:<namespace>, JWKS + conexão admin obrigatórios em cloud, senhas
(tenant + admin) resolvidas via Vault com degradação graciosa p/ env, e uma linha JSON
por log record com identidade do serviço + campos de correlação.
"""

from __future__ import annotations

import json
import logging

import pytest
from platform_database.settings import AdminDBSettings, DBSettings

from src.config import settings as S
from src.config.logging import JsonLogFormatter, configure_logging
from src.config.settings import NAMESPACE, DocsSettings, Settings, load_secret


def _settings(**overrides) -> DocsSettings:
    base = {
        "MCP_TWIN_AUDIENCE": f"mcp:{NAMESPACE}",
        "URL_ADMIN_TWIN_JWKS": "http://admin.local/jwks.json",
        "ADMIN_DB_HOST": "admin-mysql",
        "ADMIN_DB_PASSWORD": "pw",
    }
    base.update(overrides)
    return DocsSettings(**base)


# ── Alias de compatibilidade ──────────────────────────────────────────────────
def test_settings_alias_points_to_docs_settings():
    assert Settings is DocsSettings


# ── RUNTIME_ENV ───────────────────────────────────────────────────────────────
def test_runtime_env_normalizes_and_defaults():
    assert _settings(RUNTIME_ENV="  Cloud ").runtime_env == "cloud"
    assert _settings(RUNTIME_ENV="LOCAL").runtime_env == "local"


def test_runtime_env_rejects_unknown():
    with pytest.raises(ValueError):
        _settings(RUNTIME_ENV="staging")


# ── Conformidade com os protocolos do ORM ─────────────────────────────────────
def test_satisfies_orm_protocols():
    s = _settings()
    assert isinstance(s, DBSettings)
    assert isinstance(s, AdminDBSettings)
    assert s.DB_ENGINE == "mysql"  # dual-db: engine default


# ── enforce_security_invariants ───────────────────────────────────────────────
def test_enforce_ok_local():
    # Não levanta: docs off, aud mcp:, local dispensa JWKS/admin.
    DocsSettings().enforce_security_invariants()


def test_enforce_ok_cloud_with_jwks_and_admin():
    _settings(RUNTIME_ENV="cloud").enforce_security_invariants()


def test_enforce_blocks_docs_enabled():
    with pytest.raises(RuntimeError, match="STD-SEC-001"):
        _settings(DOCS_ENABLED=True).enforce_security_invariants()


def test_enforce_blocks_bad_audience():
    with pytest.raises(RuntimeError, match="STD-SEC-006"):
        _settings(MCP_TWIN_AUDIENCE="docs-mcp").enforce_security_invariants()


def test_enforce_cloud_requires_jwks():
    with pytest.raises(RuntimeError, match="URL_ADMIN_TWIN_JWKS"):
        _settings(RUNTIME_ENV="cloud", URL_ADMIN_TWIN_JWKS="").enforce_security_invariants()


def test_enforce_cloud_requires_admin_db():
    with pytest.raises(RuntimeError, match="STD-SEC-004"):
        _settings(RUNTIME_ENV="cloud", ADMIN_DB_PASSWORD="").enforce_security_invariants()
    with pytest.raises(RuntimeError, match="STD-SEC-004"):
        _settings(RUNTIME_ENV="cloud", ADMIN_DB_HOST="").enforce_security_invariants()


# ── load_secret (Vault-fallback) ──────────────────────────────────────────────
def test_load_secret_env_when_no_vault(monkeypatch):
    monkeypatch.delenv("VAULT_ADDR", raising=False)
    assert load_secret("docs-mcp/db_password", "from-env") == "from-env"


def test_load_secret_degrades_gracefully_when_vault_unavailable(monkeypatch):
    # VAULT_ADDR setado mas platform_crypto ausente → degrada p/ env (boot não quebra).
    monkeypatch.setenv("VAULT_ADDR", "http://vault.local:8200")
    assert load_secret("docs-mcp/db_password", "from-env") == "from-env"


def test_settings_resolves_secrets_via_vault(monkeypatch):
    monkeypatch.setattr(S, "load_secret", lambda _key, fallback: "resolved-pw")
    s = DocsSettings(DB_PASSWORD="ignored", ADMIN_DB_PASSWORD="ignored")
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
    rec.tool = "scan_docs"
    payload = json.loads(JsonLogFormatter().format(rec))
    assert payload["tenant_id"] == "T-1"
    assert payload["tool"] == "scan_docs"


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
    configure_logging(_settings(MCP_SERVICE_LOG_LEVEL="WARNING"))
    root = logging.getLogger()
    assert len(root.handlers) == 1
    assert isinstance(root.handlers[0].formatter, JsonLogFormatter)
    assert root.level == logging.WARNING
    # idempotente: não acumula handlers
    configure_logging(_settings())
    assert len(logging.getLogger().handlers) == 1
