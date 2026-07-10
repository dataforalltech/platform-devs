"""Testes de config: RUNTIME_ENV, enforce_security_invariants (STD-SEC-001/006)
e o logging estruturado JSON (STD-OBS-001).

Estes travam o contrato de compliance Tier-2: docs sempre off, audiência do inner
token no formato mcp:<namespace>, JWKS obrigatório em cloud, e uma linha JSON por
log record com identidade do serviço + campos de correlação.
"""

from __future__ import annotations

import json
import logging

import pytest

from src.config.logging import JsonLogFormatter, configure_logging
from src.config.settings import NAMESPACE, Settings


def _settings(**overrides) -> Settings:
    base = {
        "MCP_TWIN_AUDIENCE": f"mcp:{NAMESPACE}",
        "URL_ADMIN_TWIN_JWKS": "http://admin.local/jwks.json",
        "DOCS_ENABLED": False,
        "RUNTIME_ENV": "local",
    }
    base.update(overrides)
    return Settings(**base)


# ── RUNTIME_ENV ───────────────────────────────────────────────────────────────
def test_runtime_env_normalizes_and_defaults():
    assert _settings(RUNTIME_ENV="  Cloud ").runtime_env == "cloud"
    assert _settings(RUNTIME_ENV="LOCAL").runtime_env == "local"


def test_runtime_env_rejects_unknown():
    with pytest.raises(ValueError):
        _settings(RUNTIME_ENV="staging")


# ── enforce_security_invariants ───────────────────────────────────────────────
def test_enforce_ok_local():
    # Não levanta: docs off, aud mcp:, local dispensa JWKS.
    _settings().enforce_security_invariants()


def test_enforce_ok_cloud_with_jwks():
    _settings(RUNTIME_ENV="cloud").enforce_security_invariants()


def test_enforce_blocks_docs_enabled():
    with pytest.raises(RuntimeError, match="STD-SEC-001"):
        _settings(DOCS_ENABLED=True).enforce_security_invariants()


def test_enforce_blocks_bad_audience():
    with pytest.raises(RuntimeError, match="STD-SEC-006"):
        _settings(MCP_TWIN_AUDIENCE="architecture-mcp").enforce_security_invariants()


def test_enforce_cloud_requires_jwks():
    with pytest.raises(RuntimeError, match="URL_ADMIN_TWIN_JWKS"):
        _settings(RUNTIME_ENV="cloud", URL_ADMIN_TWIN_JWKS="").enforce_security_invariants()


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
    configure_logging(_settings(log_level="WARNING"))
    root = logging.getLogger()
    assert len(root.handlers) == 1
    assert isinstance(root.handlers[0].formatter, JsonLogFormatter)
    assert root.level == logging.WARNING
    # idempotente: não acumula handlers
    configure_logging(_settings())
    assert len(logging.getLogger().handlers) == 1
