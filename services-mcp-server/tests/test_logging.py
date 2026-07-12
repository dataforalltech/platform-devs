"""Testes do logging estruturado JSON (STD-OBS-001)."""

from __future__ import annotations

import json
import logging

from src.config.logging import JsonLogFormatter, configure_logging
from src.config.settings import ServicesSettings


def _record(**kwargs: object) -> logging.LogRecord:
    rec = logging.LogRecord(
        name="services.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello %s",
        args=("world",),
        exc_info=None,
    )
    for k, v in kwargs.items():
        setattr(rec, k, v)
    return rec


def test_formatter_emits_json_with_service_and_msg():
    payload = json.loads(JsonLogFormatter().format(_record()))
    assert payload["service"] == "services-mcp"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "services.test"
    assert payload["msg"] == "hello world"
    assert "ts" in payload


def test_formatter_includes_correlation_fields_when_present():
    payload = json.loads(
        JsonLogFormatter().format(_record(tenant_id="T-1", tool="register_service", trace_id="abc"))
    )
    assert payload["tenant_id"] == "T-1"
    assert payload["tool"] == "register_service"
    assert payload["trace_id"] == "abc"


def test_formatter_omits_absent_correlation_fields():
    payload = json.loads(JsonLogFormatter().format(_record()))
    assert "tenant_id" not in payload
    assert "tool" not in payload


def test_formatter_captures_exception_type_only():
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        rec = _record()
        rec.exc_info = sys.exc_info()
        payload = json.loads(JsonLogFormatter().format(rec))
    assert payload["exc_type"] == "ValueError"
    assert "boom" in payload["exc"]


def test_configure_logging_installs_single_json_handler():
    root = logging.getLogger()
    original = root.handlers[:]
    original_level = root.level
    try:
        configure_logging(ServicesSettings(MCP_SERVICE_LOG_LEVEL="warning"))
        assert len(root.handlers) == 1
        assert isinstance(root.handlers[0].formatter, JsonLogFormatter)
        assert root.level == logging.WARNING
    finally:
        root.handlers[:] = original
        root.setLevel(original_level)
