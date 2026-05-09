"""Logging estruturado para o servidor MCP.

Logs vão sempre para stderr — stdout é reservado para o protocolo MCP via stdio.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime
from typing import Any


class _JsonFormatter(logging.Formatter):
    """Formatter mínimo: emite uma linha JSON por log record."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        extras = getattr(record, "extras", None)
        if isinstance(extras, dict):
            payload["extras"] = extras
        return json.dumps(payload, ensure_ascii=False, default=str)


_CONFIGURED = False


def setup_logging(level: str = "INFO", fmt: str = "json") -> None:
    """Configura o root logger uma única vez."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    handler = logging.StreamHandler(stream=sys.stderr)
    if fmt == "json":
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        )

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Atalho para obter logger nomeado."""
    return logging.getLogger(name)
