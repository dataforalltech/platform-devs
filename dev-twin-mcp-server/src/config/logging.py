"""Logging estruturado (JSON) — STD-OBS-001.

Sidecar mcp_http: logs sempre estruturados, com identidade do serviço e campos de
correlação (`trace_id`/`tenant_id`/`tool`) quando presentes no record via `extra=`.
Tokens e argumentos sensíveis NUNCA são logados (STD-MCP-001 CI-4/CI-5, SEC-013:
readiness/health logam só o TIPO do erro). OTEL/Prometheus são opt-in de cloud
(providos por lib compartilhada, não reimplementados aqui).
"""

from __future__ import annotations

import json
import logging

from .settings import NAMESPACE, DevTwinSettings

_CORRELATION_FIELDS = ("trace_id", "tenant_id", "correlation_id", "tool")


class JsonLogFormatter(logging.Formatter):
    """Formata cada record como uma linha JSON (service, level, logger, msg + correlação)."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "service": NAMESPACE,
            "msg": record.getMessage(),
        }
        for field in _CORRELATION_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        if record.exc_info:
            # Só o TIPO da exceção no campo estruturado; o traceback completo vai em 'exc'.
            payload["exc_type"] = record.exc_info[0].__name__ if record.exc_info[0] else None
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(settings: DevTwinSettings) -> None:
    """Instala o handler JSON no root logger (idempotente). Chamado em build_server()."""
    handler = logging.StreamHandler()
    handler.setFormatter(JsonLogFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(settings.log_level.upper())
