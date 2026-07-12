"""Logging estruturado (JSON) — STD-OBS-001.

Sidecar mcp_http: logs sempre estruturados, com identidade do serviço e campos de
correlação (`trace_id`/`tenant_id`/`correlation_id`/`tool`). Os campos são preenchidos
POR-REQUEST via ContextVars (ligados pelo sidecar HTTP: `trace_id`/`correlation_id` no
middleware; `tenant_id`/`tool` no handler pós-verificação do inner token) e injetados em
cada record pelo `CorrelationFilter` — de modo que TODO log emitido durante a request os
carrega, sem precisar passá-los em cada chamada (T-OBS / CI-8). Um valor passado
explicitamente via `extra=` tem precedência sobre o ContextVar.
Tokens e argumentos sensíveis NUNCA são logados (STD-MCP-001 CI-4/CI-5, SEC-013:
readiness/health logam só o TIPO do erro). OTEL/Prometheus são opt-in de cloud
(providos por lib compartilhada, não reimplementados aqui).
"""

from __future__ import annotations

import contextvars
import json
import logging

from .settings import NAMESPACE, Settings

_CORRELATION_FIELDS = ("trace_id", "tenant_id", "correlation_id", "tool")

# ContextVars por-request (um por campo de correlação). Preenchidos pelo sidecar HTTP e
# lidos pelo CorrelationFilter no momento do emit. Default None = campo ausente no log.
_CONTEXT_VARS: dict[str, contextvars.ContextVar[str | None]] = {
    field: contextvars.ContextVar(f"qa_mcp_log_{field}", default=None) for field in _CORRELATION_FIELDS
}


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


class CorrelationFilter(logging.Filter):
    """Injeta os campos de correlação (dos ContextVars por-request) em cada record.

    Um valor já presente no record (passado explicitamente via `extra=`) tem precedência
    sobre o ContextVar. Sempre retorna True — o filtro só enriquece, nunca descarta."""

    def filter(self, record: logging.LogRecord) -> bool:
        for field, var in _CONTEXT_VARS.items():
            if getattr(record, field, None) is None:
                value = var.get()
                if value is not None:
                    setattr(record, field, value)
        return True


def bind_log_context(
    **fields: str | None,
) -> dict[str, contextvars.Token[str | None]]:
    """Liga campos de correlação ao contexto atual; retorna tokens p/ `reset_log_context`.

    Só liga campos conhecidos (`_CORRELATION_FIELDS`) e não-None. Idempotente/aninhável:
    chamadas sucessivas empilham valores que `reset_log_context` desfaz na ordem inversa."""
    tokens: dict[str, contextvars.Token[str | None]] = {}
    for field, value in fields.items():
        var = _CONTEXT_VARS.get(field)
        if var is not None and value is not None:
            tokens[field] = var.set(value)
    return tokens


def reset_log_context(tokens: dict[str, contextvars.Token[str | None]]) -> None:
    """Desfaz um `bind_log_context` (restaura o valor anterior de cada ContextVar)."""
    for field, token in tokens.items():
        _CONTEXT_VARS[field].reset(token)


def configure_logging(settings: Settings) -> None:
    """Instala o handler JSON no root logger (idempotente). Chamado em build_server()."""
    handler = logging.StreamHandler()
    handler.setFormatter(JsonLogFormatter())
    handler.addFilter(CorrelationFilter())  # enriquece cada record com a correlação por-request
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(settings.log_level.upper())
