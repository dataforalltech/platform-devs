"""Testes do logging estruturado JSON (STD-OBS-001)."""

from __future__ import annotations

import json
import logging

from src.config.logging import JsonLogFormatter, configure_logging
from src.config.settings import Settings


def _record(**extra) -> logging.LogRecord:
    rec = logging.LogRecord(
        name="test.logger",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello %s",
        args=("world",),
        exc_info=None,
    )
    for k, v in extra.items():
        setattr(rec, k, v)
    return rec


def test_format_basic_fields():
    payload = json.loads(JsonLogFormatter().format(_record()))
    assert payload["service"] == "config-mcp"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "test.logger"
    assert payload["msg"] == "hello world"


def test_format_includes_correlation_fields():
    payload = json.loads(JsonLogFormatter().format(_record(tenant_id="T-1", tool="get_env_config")))
    assert payload["tenant_id"] == "T-1"
    assert payload["tool"] == "get_env_config"


def test_format_exception_only_type_and_traceback():
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        rec = _record()
        rec.exc_info = sys.exc_info()
    payload = json.loads(JsonLogFormatter().format(rec))
    assert payload["exc_type"] == "ValueError"
    assert "boom" in payload["exc"]


def test_configure_logging_installs_json_handler():
    settings = Settings(MCP_SERVICE_LOG_LEVEL="DEBUG", _env_file=None)
    configure_logging(settings)
    root = logging.getLogger()
    assert len(root.handlers) == 1
    assert isinstance(root.handlers[0].formatter, JsonLogFormatter)
    assert root.level == logging.DEBUG
