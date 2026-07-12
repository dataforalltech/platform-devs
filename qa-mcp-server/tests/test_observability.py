"""Rastreabilidade por-request (T-OBS / CI-8): correlação nos logs + echo de headers.

NÃO toca banco. Exercita o middleware ASGI (echo `X-Request-Id`/`X-Correlation-Id`)
pelos caminhos pré-DB (/v1/health, /mcp/tools/list, /mcp/tools/call sem token → 401) e o
`CorrelationFilter`/`bind_log_context` como unidades puras. A verificação RS256 e o
caminho com estado (MySQL real) já são cobertos em test_mcp_server.py.
"""

from __future__ import annotations

import json
import logging

from fastapi.testclient import TestClient

from src.config.logging import (
    CorrelationFilter,
    JsonLogFormatter,
    bind_log_context,
    reset_log_context,
)
from src.config.settings import QASettings
from src.server import mcp_server as M


def _client() -> TestClient:
    return TestClient(
        M._build_http_app(
            QASettings(
                MCP_TWIN_AUDIENCE="mcp:qa-mcp",
                URL_ADMIN_TWIN_JWKS="http://admin.local/jwks.json",
            )
        )
    )


# ── Echo de headers (gera quando ausente / honra o do cliente) ────────────────
def test_health_generates_correlation_headers():
    r = _client().get("/v1/health")
    assert r.status_code == 200
    # gerado (sem header do cliente) → request-id presente e == correlation-id.
    assert r.headers["x-request-id"]
    assert r.headers["x-request-id"] == r.headers["x-correlation-id"]


def test_generated_request_id_is_unique_per_request():
    client = _client()
    first = client.get("/v1/health").headers["x-request-id"]
    second = client.get("/v1/health").headers["x-request-id"]
    assert first != second


def test_client_request_id_is_honored():
    r = _client().get("/v1/health", headers={"X-Request-Id": "req-abc-123"})
    assert r.headers["x-request-id"] == "req-abc-123"
    # sem X-Correlation-Id do cliente, correlation herda o request-id.
    assert r.headers["x-correlation-id"] == "req-abc-123"


def test_client_correlation_id_is_honored():
    r = _client().get("/v1/health", headers={"X-Correlation-Id": "corr-xyz"})
    assert r.headers["x-correlation-id"] == "corr-xyz"
    # sem X-Request-Id, o request-id cai no correlation-id fornecido.
    assert r.headers["x-request-id"] == "corr-xyz"


def test_tools_list_echoes_headers():
    r = _client().get("/mcp/tools/list", headers={"X-Request-Id": "req-list"})
    assert r.status_code == 200
    assert r.headers["x-request-id"] == "req-list"


def test_tools_call_pre_db_path_still_echoes_headers():
    # caminho pré-DB (sem token → 401): ainda assim ecoa o request-id do cliente.
    r = _client().post(
        "/mcp/tools/call",
        json={"params": {"name": "generate_qa_report", "arguments": {"repo_path": "/r"}}},
        headers={"X-Request-Id": "req-401"},
    )
    assert r.status_code == 401
    assert r.headers["x-request-id"] == "req-401"


# ── CorrelationFilter + bind/reset (unidades puras, sem HTTP) ─────────────────
def _record() -> logging.LogRecord:
    return logging.LogRecord("qa.test", logging.INFO, __file__, 1, "msg", None, None)


def test_filter_injects_context_into_record():
    tokens = bind_log_context(trace_id="tr-1", tenant_id="T-9", tool="run_linter")
    try:
        rec = _record()
        assert CorrelationFilter().filter(rec) is True
        payload = json.loads(JsonLogFormatter().format(rec))
        assert payload["trace_id"] == "tr-1"
        assert payload["tenant_id"] == "T-9"
        assert payload["tool"] == "run_linter"
    finally:
        reset_log_context(tokens)


def test_filter_is_noop_without_context():
    rec = _record()
    assert CorrelationFilter().filter(rec) is True
    payload = json.loads(JsonLogFormatter().format(rec))
    assert "trace_id" not in payload
    assert "tenant_id" not in payload


def test_explicit_record_value_takes_precedence_over_context():
    tokens = bind_log_context(tenant_id="ctx-tenant")
    try:
        rec = _record()
        rec.tenant_id = "explicit-tenant"  # passado via extra= tem precedência
        CorrelationFilter().filter(rec)
        payload = json.loads(JsonLogFormatter().format(rec))
        assert payload["tenant_id"] == "explicit-tenant"
    finally:
        reset_log_context(tokens)


def test_bind_ignores_unknown_and_none_fields():
    tokens = bind_log_context(trace_id="tr", tenant_id=None, unknown_field="x")
    try:
        assert set(tokens) == {"trace_id"}  # None e campo desconhecido são ignorados
    finally:
        reset_log_context(tokens)


def test_reset_restores_previous_context():
    outer = bind_log_context(trace_id="outer")
    try:
        inner = bind_log_context(trace_id="inner")
        reset_log_context(inner)
        rec = _record()
        CorrelationFilter().filter(rec)
        assert rec.trace_id == "outer"  # reset do inner restaura o valor externo
    finally:
        reset_log_context(outer)
