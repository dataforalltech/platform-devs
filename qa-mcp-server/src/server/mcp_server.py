"""Servidor MCP do qa-mcp — sidecar kind=mcp_http, GATEWAY-READY (Model C).

Reescrito para o padrão canônico do platform-service-template (v2.0). Implementa o
contrato de integração com o MCP Gateway central (platform-mcp-gateway):
  - docs/standards/STD-MCP-001-mcp-gateway-integration-contract.md  (CI-1..CI-11)
  - docs/standards/STD-SEC-006-token-model-c-inner-token.md          (inner token / audiência)

Pontos gateway-ready:
  1. /mcp/tools/list emite, por tool, inputSchema type=object + capability +
     required_scope + resource_type + data_domain (o gateway NÃO deriva por nome).
  2. /mcp/tools/call re-verifica o **inner Twin Token** (aud=mcp:qa-mcp) via JWKS do
     platform-admin, na PRÓPRIA audiência (defense in depth — CI-4/CI-5). O inner
     token chega em params._meta.twin_token.
  3. tenant_id vem SEMPRE dos claims do token verificado — nunca de argumento do
     cliente (SEC-035 / INV-3).
  4. _EXEMPT_TOOLS (status, sem token) e _EXCLUDE_TOOLS (denylist fail-safe).
  5. /docs desabilitado (DOCS_ENABLED=false — HTTP-01).

Transporte: stdio (primário, MCP) + sidecar HTTP (:MCP_PORT, default 7100):
  GET  /v1/health        — liveness (health_path do registro, sem token)
  GET  /mcp/tools/list   — catálogo governado (com metadados de policy)
  POST /mcp/tools/call   — execução (inner token obrigatório, exceto _EXEMPT_TOOLS)

NOTA: qa-mcp executa testes/análises e PERSISTE runs num log append-only sobre o ORM
canônico (`platform_database.orm`), **tenant-scoped e dual-db** (MySQL banco-por-tenant /
PostgreSQL schema-por-tenant). Não há backend REST intermediário (sem ServiceApiClient).
Não há store global: a persistência é resolvida por-request, credencial-zero — cada
chamada abre uma sessão tenant-scoped (`for_tenant`) a partir do tenant nos claims do
inner token verificado. A tool `status` é compute-only (tokenless, sem tenant/store).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any
from uuid import uuid4

import jwt  # PyJWT — verificação RS256 do inner token via JWKS
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from mcp.server import Server
from mcp.types import TextContent, Tool
from platform_database import close_tenant_pools
from platform_database.orm import configure, for_tenant
from platform_database.orm.dialects import dialect_for_pool
from platform_database.tenant_resolver import get_pool_for_tenant
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ..config.logging import bind_log_context, configure_logging, reset_log_context
from ..config.settings import NAMESPACE, QASettings, get_settings
from ..db.schema import ensure_schema
from ..db.store import QAStore
from ..tools.analysis_tool import (
    analyze_complexity,
    check_dependencies,
    run_linter,
    run_security_scan,
    run_type_check,
)
from ..tools.api_tool import generate_test_matrix, run_api_tests
from ..tools.browser_tool import check_accessibility, screenshot_page, visual_regression
from ..tools.report_tool import generate_qa_report, get_coverage_report
from ..tools.test_tool import run_e2e_tests, run_unit_tests

_log = logging.getLogger(__name__)

# ── Tool Schemas + Policy metadata (STD-MCP-001 CI-2) ─────────────────────────
# Cada tool declara, além de description/schema, os 4 campos de política:
#   capability     — id estável <namespace>.<tool> (não derivar por nome no gateway)
#   required_scope — escopo de execução no formato dominio:tipo:acao (least-privilege)
#   resource_type  — tipo de recurso tocado
#   data_domain    — domínio de dado (governa HITL floor / classificação LGPD)
# inputSchema MUST ser type=object com properties (senão a validação no front-door
# é fail-open). Execuções/geração de artefatos usam :write; análise/relatório :read.
# ─────────────────────────────────────────────────────────────────────────────
_TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "status": {
        "description": "Retorna o status real do servidor (nome, versão, nº de tools).",
        "capability": "qa-mcp.status",
        "required_scope": "qa-mcp:status:read",
        "resource_type": "status",
        "data_domain": "operational",
        "schema": {"type": "object", "additionalProperties": False, "properties": {}},
    },
    "run_unit_tests": {
        "description": (
            "Roda testes unitários (pytest/jest) com cobertura opcional. Detecta framework automaticamente."
        ),
        "capability": "qa-mcp.run_unit_tests",
        "required_scope": "qa-mcp:test:write",
        "resource_type": "test_run",
        "data_domain": "quality",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "repo_path": {
                    "type": "string",
                    "description": "Caminho absoluto do repositório",
                },
                "framework": {
                    "type": "string",
                    "enum": ["auto", "pytest", "jest"],
                    "default": "auto",
                },
                "test_path": {"type": "string", "default": "."},
                "coverage": {"type": "boolean", "default": False},
                "timeout": {
                    "type": "integer",
                    "description": "Timeout em segundos",
                },
            },
            "required": ["repo_path"],
        },
    },
    "run_e2e_tests": {
        "description": (
            "Roda testes E2E via Playwright (test_*.py ou *.spec.ts). "
            "Detecta tipo de arquivo e usa comando correto."
        ),
        "capability": "qa-mcp.run_e2e_tests",
        "required_scope": "qa-mcp:test:write",
        "resource_type": "test_run",
        "data_domain": "quality",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "test_path": {
                    "type": "string",
                    "description": "Diretório com os testes E2E",
                },
                "base_url": {
                    "type": "string",
                    "description": "URL base da aplicação",
                },
                "browser": {
                    "type": "string",
                    "enum": ["chromium", "firefox", "webkit"],
                    "default": "chromium",
                },
                "headless": {"type": "boolean", "default": True},
                "timeout": {
                    "type": "integer",
                    "description": "Timeout em segundos",
                },
            },
            "required": ["test_path", "base_url"],
        },
    },
    "run_api_tests": {
        "description": (
            "Testa endpoints HTTP com verificação de status e chaves de resposta. "
            "Suporta GET, POST, PUT, DELETE com headers e body customizados."
        ),
        "capability": "qa-mcp.run_api_tests",
        "required_scope": "qa-mcp:test:write",
        "resource_type": "test_run",
        "data_domain": "quality",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "base_url": {
                    "type": "string",
                    "description": "URL base da API (ex: http://localhost:8000)",
                },
                "endpoints": {
                    "type": "array",
                    "description": "Lista de endpoints a testar",
                    "items": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "method": {"type": "string"},
                            "headers": {"type": "object"},
                            "body": {"type": "object"},
                            "expect_status": {"type": "integer"},
                            "expect_keys": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                        },
                        "required": ["path"],
                    },
                },
                "timeout": {
                    "type": "number",
                    "description": "Timeout HTTP em segundos",
                },
            },
            "required": ["base_url", "endpoints"],
        },
    },
    "generate_test_matrix": {
        "description": (
            "Gera e executa matriz de testes: cada cenário × payload é um caso. "
            "Ideal para testar variações de input em endpoints."
        ),
        "capability": "qa-mcp.generate_test_matrix",
        "required_scope": "qa-mcp:test:write",
        "resource_type": "test_run",
        "data_domain": "quality",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "base_url": {"type": "string"},
                "scenarios": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "endpoint": {"type": "string"},
                            "method": {"type": "string"},
                            "payloads": {
                                "type": "array",
                                "items": {"type": "object"},
                            },
                            "expected_statuses": {
                                "type": "array",
                                "items": {"type": "integer"},
                            },
                            "expected_keys": {
                                "type": "array",
                                "items": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                            },
                        },
                        "required": ["name", "endpoint"],
                    },
                },
            },
            "required": ["base_url", "scenarios"],
        },
    },
    "screenshot_page": {
        "description": (
            "Tira screenshot de uma página via Playwright. "
            "Suporta viewports desktop/tablet/mobile e captura de elemento por selector."
        ),
        "capability": "qa-mcp.screenshot_page",
        "required_scope": "qa-mcp:screenshot:write",
        "resource_type": "screenshot",
        "data_domain": "quality",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "url": {"type": "string", "description": "URL da página"},
                "viewport": {
                    "type": "string",
                    "enum": ["desktop", "tablet", "mobile"],
                    "default": "desktop",
                },
                "selector": {
                    "type": "string",
                    "description": "CSS selector para capturar elemento específico",
                },
                "output_dir": {
                    "type": "string",
                    "description": "Diretório de saída (default: settings.screenshots_dir)",
                },
            },
            "required": ["url"],
        },
    },
    "check_accessibility": {
        "description": (
            "Verifica acessibilidade via Playwright + axe-core. "
            "Suporta WCAG2A, WCAG2AA, WCAG2AAA. Retorna violations, passes e incomplete."
        ),
        "capability": "qa-mcp.check_accessibility",
        "required_scope": "qa-mcp:accessibility:read",
        "resource_type": "accessibility_report",
        "data_domain": "quality",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "url": {"type": "string", "description": "URL da página a verificar"},
                "standard": {
                    "type": "string",
                    "enum": ["WCAG2A", "WCAG2AA", "WCAG2AAA"],
                    "default": "WCAG2AA",
                },
            },
            "required": ["url"],
        },
    },
    "visual_regression": {
        "description": (
            "Compara screenshot atual com baseline via Pillow. "
            "Cria baseline se não existir. Retorna diff em % de pixels."
        ),
        "capability": "qa-mcp.visual_regression",
        "required_scope": "qa-mcp:visual:write",
        "resource_type": "visual_diff",
        "data_domain": "quality",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "url": {"type": "string"},
                "baseline_name": {
                    "type": "string",
                    "description": "Nome do baseline (sem extensão)",
                },
                "viewport": {
                    "type": "string",
                    "enum": ["desktop", "tablet", "mobile"],
                    "default": "desktop",
                },
                "threshold_pct": {
                    "type": "number",
                    "description": "% máximo de pixels diferentes para passar",
                    "default": 2.0,
                },
                "update_baseline": {
                    "type": "boolean",
                    "description": "Se True, salva novo baseline",
                    "default": False,
                },
            },
            "required": ["url", "baseline_name"],
        },
    },
    "run_linter": {
        "description": (
            "Análise estática com ruff (Python) ou eslint (JS/TS). "
            "Detecta framework automaticamente. Suporta fix automático."
        ),
        "capability": "qa-mcp.run_linter",
        "required_scope": "qa-mcp:analysis:read",
        "resource_type": "analysis",
        "data_domain": "quality",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "repo_path": {"type": "string"},
                "framework": {
                    "type": "string",
                    "enum": ["auto", "python", "javascript", "typescript"],
                    "default": "auto",
                },
                "fix": {
                    "type": "boolean",
                    "default": False,
                    "description": "Aplicar correções automáticas",
                },
            },
            "required": ["repo_path"],
        },
    },
    "run_security_scan": {
        "description": (
            "Scan de segurança com bandit (Python) ou npm audit (JS/TS). "
            "Classifica por severity: HIGH, MEDIUM, LOW."
        ),
        "capability": "qa-mcp.run_security_scan",
        "required_scope": "qa-mcp:security:read",
        "resource_type": "security_scan",
        "data_domain": "quality",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "repo_path": {"type": "string"},
                "framework": {
                    "type": "string",
                    "enum": ["auto", "python", "javascript", "typescript"],
                    "default": "auto",
                },
            },
            "required": ["repo_path"],
        },
    },
    "check_dependencies": {
        "description": (
            "Verifica vulnerabilidades em dependências com pip-audit/safety (Python) "
            "ou npm audit (Node). Detecta tipo de projeto automaticamente."
        ),
        "capability": "qa-mcp.check_dependencies",
        "required_scope": "qa-mcp:dependency:read",
        "resource_type": "dependency_scan",
        "data_domain": "quality",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "repo_path": {"type": "string"},
            },
            "required": ["repo_path"],
        },
    },
    "run_type_check": {
        "description": (
            "Type checking com mypy (Python) ou tsc (TypeScript). Retorna erros e warnings por arquivo."
        ),
        "capability": "qa-mcp.run_type_check",
        "required_scope": "qa-mcp:analysis:read",
        "resource_type": "analysis",
        "data_domain": "quality",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "repo_path": {"type": "string"},
                "framework": {
                    "type": "string",
                    "enum": ["auto", "python", "javascript", "typescript"],
                    "default": "auto",
                },
            },
            "required": ["repo_path"],
        },
    },
    "analyze_complexity": {
        "description": (
            "Analisa complexidade ciclomática com radon (Python) ou grep simples (JS/TS). "
            "Identifica hotspots acima do threshold."
        ),
        "capability": "qa-mcp.analyze_complexity",
        "required_scope": "qa-mcp:analysis:read",
        "resource_type": "analysis",
        "data_domain": "quality",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "repo_path": {"type": "string"},
                "threshold": {
                    "type": "integer",
                    "description": "CC máximo antes de considerar complexo (default: complexity_threshold)",
                },
            },
            "required": ["repo_path"],
        },
    },
    "get_coverage_report": {
        "description": (
            "Lê relatório de cobertura de testes. "
            "Python: coverage.json; Jest: coverage/coverage-summary.json."
        ),
        "capability": "qa-mcp.get_coverage_report",
        "required_scope": "qa-mcp:coverage:read",
        "resource_type": "coverage_report",
        "data_domain": "quality",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "repo_path": {"type": "string"},
                "framework": {
                    "type": "string",
                    "enum": ["auto", "python", "javascript", "typescript"],
                    "default": "auto",
                },
            },
            "required": ["repo_path"],
        },
    },
    "generate_qa_report": {
        "description": (
            "Gera relatório QA agregado com score 0-100 e grade A-F. "
            "Pondera: unit_tests 30%, security 25%, linter 20%, coverage 15%, dependencies 10%."
        ),
        "capability": "qa-mcp.generate_qa_report",
        "required_scope": "qa-mcp:report:read",
        "resource_type": "qa_report",
        "data_domain": "quality",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "repo_path": {"type": "string"},
                "last_n_runs": {
                    "type": "integer",
                    "description": "Considera último N run de cada tipo",
                    "default": 1,
                },
            },
            "required": ["repo_path"],
        },
    },
}

# status é encaminhada SEM inner token (CI-7 exempt_tools — só tokenless).
_EXEMPT_TOOLS: frozenset[str] = frozenset({"status"})
# Denylist fail-safe: tools que retornam segredos NUNCA saem pelo gateway (CI-7).
_EXCLUDE_TOOLS: frozenset[str] = frozenset()

# Campos de policy repassados no /mcp/tools/list (o gateway lê estes campos).
_POLICY_FIELDS = ("capability", "required_scope", "resource_type", "data_domain")


def _status() -> dict[str, Any]:
    """Status real do servidor (compute-only, sem store)."""
    return {
        "status": "ok",
        "service": NAMESPACE,
        "version": "0.1.0",
        "tools": len(_TOOL_SCHEMAS),
    }


# ── Verificação do inner Twin Token (STD-SEC-006 / CI-4/CI-5) ─────────────────


def _verify_inner_token(twin_token: str, settings: QASettings) -> dict[str, Any]:
    """Re-verifica o inner Twin Token na PRÓPRIA audiência (mcp:qa-mcp).

    O gateway já verificou o front token; o backend é 'one more verified client'
    (defense in depth). RS256 via JWKS do platform-admin; audiência exata; jti
    obrigatório. Levanta em qualquer falha (fail-closed).
    """
    if not settings.mcp_twin_audience or not settings.url_admin_twin_jwks:
        raise PermissionError(
            "integração com o gateway não configurada: defina MCP_TWIN_AUDIENCE "
            "(mcp:qa-mcp) e URL_ADMIN_TWIN_JWKS (ver STD-SEC-006 / IT-006)."
        )
    signing_key = jwt.PyJWKClient(settings.url_admin_twin_jwks).get_signing_key_from_jwt(twin_token)
    return jwt.decode(
        twin_token,
        signing_key.key,
        algorithms=["RS256"],  # RS256 exclusivo (STD-SEC-001)
        audience=settings.mcp_twin_audience,  # a falha de integração nº 1
        options={"require": ["exp", "aud", "jti"]},  # sem jti → rejeita (JTI_REQUIRED)
    )


# ── Dispatcher (async; store tenant-scoped ligado ao pool do tenant) ──────────


async def _dispatch(name: str, args: dict[str, Any], settings: QASettings, store: QAStore) -> dict:
    """Despacha a chamada para a função de tool (async). O tenant NÃO viaja nos args
    (INV-3): o ``store`` já está ligado ao pool do tenant (resolvido dos claims)."""
    if name == "status":
        return _status()
    # ---- test_tool ----
    if name == "run_unit_tests":
        return await run_unit_tests(
            store,
            settings,
            repo_path=args.get("repo_path", ""),
            framework=args.get("framework", "auto"),
            test_path=args.get("test_path", "."),
            coverage=args.get("coverage", False),
            timeout=args.get("timeout"),
        )
    if name == "run_e2e_tests":
        return await run_e2e_tests(
            store,
            settings,
            test_path=args.get("test_path", ""),
            base_url=args.get("base_url", ""),
            browser=args.get("browser", "chromium"),
            headless=args.get("headless", True),
            timeout=args.get("timeout"),
        )
    # ---- api_tool ----
    if name == "run_api_tests":
        return await run_api_tests(
            store,
            settings,
            base_url=args.get("base_url", ""),
            endpoints=args.get("endpoints") or [],
            timeout=args.get("timeout"),
        )
    if name == "generate_test_matrix":
        return await generate_test_matrix(
            store,
            settings,
            base_url=args.get("base_url", ""),
            scenarios=args.get("scenarios") or [],
        )
    # ---- browser_tool ----
    if name == "screenshot_page":
        return await screenshot_page(
            store,
            settings,
            url=args.get("url", ""),
            viewport=args.get("viewport", "desktop"),
            selector=args.get("selector"),
            output_dir=args.get("output_dir"),
        )
    if name == "check_accessibility":
        return await check_accessibility(
            store,
            settings,
            url=args.get("url", ""),
            standard=args.get("standard", "WCAG2AA"),
        )
    if name == "visual_regression":
        return await visual_regression(
            store,
            settings,
            url=args.get("url", ""),
            baseline_name=args.get("baseline_name", ""),
            viewport=args.get("viewport", "desktop"),
            threshold_pct=args.get("threshold_pct", 2.0),
            update_baseline=args.get("update_baseline", False),
        )
    # ---- analysis_tool ----
    if name == "run_linter":
        return await run_linter(
            store,
            settings,
            repo_path=args.get("repo_path", ""),
            framework=args.get("framework", "auto"),
            fix=args.get("fix", False),
        )
    if name == "run_security_scan":
        return await run_security_scan(
            store,
            settings,
            repo_path=args.get("repo_path", ""),
            framework=args.get("framework", "auto"),
        )
    if name == "check_dependencies":
        return await check_dependencies(
            store,
            settings,
            repo_path=args.get("repo_path", ""),
        )
    if name == "run_type_check":
        return await run_type_check(
            store,
            settings,
            repo_path=args.get("repo_path", ""),
            framework=args.get("framework", "auto"),
        )
    if name == "analyze_complexity":
        return await analyze_complexity(
            store,
            settings,
            repo_path=args.get("repo_path", ""),
            threshold=args.get("threshold"),
        )
    # ---- report_tool ----
    if name == "get_coverage_report":
        return await get_coverage_report(
            store,
            settings,
            repo_path=args.get("repo_path", ""),
            framework=args.get("framework", "auto"),
        )
    if name == "generate_qa_report":
        return await generate_qa_report(
            store,
            settings,
            repo_path=args.get("repo_path", ""),
            last_n_runs=args.get("last_n_runs", 1),
        )
    raise KeyError(name)


# ── Tenant plumbing (credencial-zero) ─────────────────────────────────────────
# Bootstrap de schema roda UMA vez por tenant/processo (idempotente de qualquer forma).
_SCHEMA_READY: set[str] = set()
_SCHEMA_LOCK = asyncio.Lock()


async def _ensure_tenant_schema(settings: QASettings, tenant_id: str) -> None:
    """Garante a tabela no banco do tenant (uma vez por processo). O engine é o do
    dialeto do pool resolvido — é o ponto que faz o mesmo código servir o dual-db."""
    if tenant_id in _SCHEMA_READY:
        return
    async with _SCHEMA_LOCK:
        if tenant_id in _SCHEMA_READY:
            return
        # Mesmo pool cacheado que o for_tenant usará (registry por TenantDBConfig).
        pool = await get_pool_for_tenant(settings, tenant_id, strict=True)
        await ensure_schema(pool, engine=dialect_for_pool(pool).name)
        _SCHEMA_READY.add(tenant_id)


async def _run_tool(
    name: str, arguments: dict[str, Any], settings: QASettings, tenant_id: str
) -> dict[str, Any]:
    """Abre a sessão tenant-scoped (credencial-zero), garante o schema e despacha."""
    await _ensure_tenant_schema(settings, tenant_id)
    async with for_tenant(tenant_id) as session:
        store = QAStore(session)
        return await _dispatch(name, arguments, settings, store)


# ── HTTP Sidecar ──────────────────────────────────────────────────────────────


class CorrelationMiddleware:
    """Middleware ASGI puro de rastreabilidade por-request (T-OBS / CI-8).

    Por request: deriva um request-id (honra `X-Request-Id`, senão `X-Correlation-Id`
    do cliente; senão gera um) e um correlation-id; liga ambos ao contexto de log
    (`trace_id`/`correlation_id`) para que TODO log da request os carregue; e ecoa
    `X-Request-Id`/`X-Correlation-Id` na resposta. `tenant_id`/`tool` são ligados depois,
    no handler /mcp/tools/call, só após a verificação do inner token (o tenant vem dos
    claims — nunca do cliente). ASGI puro (sem task boundary) → os ContextVars ligados
    aqui propagam para o handler; o `reset` no finally evita vazamento entre requests."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        request_id = headers.get("x-request-id") or headers.get("x-correlation-id") or uuid4().hex
        correlation_id = headers.get("x-correlation-id") or request_id
        tokens = bind_log_context(trace_id=request_id, correlation_id=correlation_id)

        async def send_with_correlation(message: Message) -> None:
            if message["type"] == "http.response.start":
                out = MutableHeaders(scope=message)
                out["x-request-id"] = request_id
                out["x-correlation-id"] = correlation_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_correlation)
        finally:
            reset_log_context(tokens)


def _build_http_app(settings: QASettings) -> FastAPI:
    """Cria o sidecar HTTP (health + bridge governado /mcp/tools/*).

    Stateless quanto a store: cada chamada (não-exempt) abre uma sessão tenant-scoped
    (credencial-zero) a partir do tenant nos claims do inner token. A tool `status` é
    exempt e compute-only (sem tenant/store)."""
    app = FastAPI(
        title="qa-mcp API",
        version="0.1.0",
        docs_url="/docs" if settings.docs_enabled else None,  # false em todo ambiente
        redoc_url=None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
    )
    # Rastreabilidade por-request: correlação nos logs + echo dos headers (T-OBS / CI-8).
    app.add_middleware(CorrelationMiddleware)

    @app.get("/v1/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "service": NAMESPACE, "tools": len(_TOOL_SCHEMAS)}

    @app.get("/mcp/tools/list")
    def http_list_tools() -> dict:
        tools = []
        for name, meta in _TOOL_SCHEMAS.items():
            entry: dict[str, Any] = {
                "name": name,
                "description": meta["description"],
                "inputSchema": meta["schema"],
            }
            entry.update({f: meta[f] for f in _POLICY_FIELDS})
            tools.append(entry)
        return {"result": {"tools": tools}}

    def _envelope(payload: dict[str, Any]) -> dict[str, Any]:
        content = [TextContent(type="text", text=json.dumps(payload, ensure_ascii=False, indent=2))]
        return {"result": {"content": [c.model_dump(exclude_none=True) for c in content]}}

    @app.post("/mcp/tools/call")
    async def http_call_tool(body: dict) -> Any:
        params = body.get("params", body)
        name = params.get("name", "")
        arguments = dict(params.get("arguments", {}) or {})

        if name in _EXCLUDE_TOOLS:
            return JSONResponse(status_code=403, content={"error": "tool_excluded", "tool": name})

        # Tools exempt (status): compute-only, tokenless, SEM tenant/store.
        if name in _EXEMPT_TOOLS:
            if name not in _TOOL_SCHEMAS:
                return JSONResponse(status_code=404, content={"error": "unknown_tool", "tool": name})
            return _envelope(_status())

        # Execução (não-exempt) exige inner token válido; tenant vem SEMPRE dos claims
        # (SEC-035 / INV-3), nunca de argumento do cliente.
        twin_token = (params.get("_meta") or {}).get("twin_token")
        if not twin_token:
            return JSONResponse(status_code=401, content={"error": "missing_twin_token"})
        try:
            claims = _verify_inner_token(twin_token, settings)
        except Exception as exc:  # noqa: BLE001 — fail-closed em qualquer falha de verificação
            _log.warning("inner_token_rejected tool=%s detail=%s", name, exc)
            return JSONResponse(status_code=401, content={"error": "invalid_twin_token"})
        tenant_id = claims.get("tenant_id")
        if not tenant_id:
            return JSONResponse(status_code=401, content={"error": "missing_tenant_scope"})

        # tenant_id vem SEMPRE dos claims verificados (SEC-035 / INV-3); liga tenant/tool
        # ao contexto de log só agora, para os logs da execução carregarem a correlação.
        ctx_tokens = bind_log_context(tenant_id=str(tenant_id), tool=name)
        try:
            payload = await _run_tool(name, arguments, settings, str(tenant_id))
        except KeyError:
            return JSONResponse(status_code=404, content={"error": "unknown_tool", "tool": name})
        except Exception as exc:  # noqa: BLE001 — a resposta carrega o erro
            _log.exception("tool_internal_error: %s", name)
            payload = {"error": "internal_error", "detail": str(exc), "tool": name}
        finally:
            reset_log_context(ctx_tokens)
        return _envelope(payload)

    @app.on_event("shutdown")
    async def _close_pools() -> None:
        # Fecha os pools por-tenant no shutdown (registry compartilhado da lib).
        await close_tenant_pools()

    return app


# ── Server (stdio + sidecar) ──────────────────────────────────────────────────


def build_server() -> tuple[Server, QASettings, FastAPI]:
    """Inicializa o MCP Server (stdio), settings e o sidecar HTTP.

    Não há store global: a persistência é tenant-scoped e resolvida por-request
    (credencial-zero). ``orm.configure(settings)`` registra a fonte admin (ADMIN_DB_*)
    usada para resolver o tenant → credencial do seu banco via PLATFORMS."""
    settings = get_settings()
    settings.enforce_security_invariants()  # fail-fast no boot (STD-SEC-001/004/006)
    configure_logging(settings)  # logging estruturado JSON (STD-OBS-001)
    configure(settings)  # bootstrap credencial-zero (ORM-H-12): admin source p/ for_tenant
    http_app = _build_http_app(settings)
    _log.info("qa_mcp_ready tools=%d engine=%s", len(_TOOL_SCHEMAS), settings.DB_ENGINE)

    server: Server = Server("qa-mcp-server")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(name=name, description=meta["description"], inputSchema=meta["schema"])
            for name, meta in _TOOL_SCHEMAS.items()
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any] | None) -> list[TextContent]:
        # `status` é compute-only (tokenless) → servida sobre stdio. As demais tools são
        # tenant-scoped e gateway-only: o transporte stdio não carrega o inner token
        # (logo, sem tenant) → recusa fail-closed. A execução real entra pelo sidecar
        # HTTP (/mcp/tools/call), onde o tenant vem dos claims verificados.
        if name == "status":
            payload: dict[str, Any] = _status()
        elif name not in _TOOL_SCHEMAS:
            payload = {"error": "unknown_tool", "tool": name}
        else:
            payload = {
                "error": "tenant_context_required",
                "tool": name,
                "detail": (
                    "qa-mcp é tenant-scoped e gateway-only; chame via o sidecar HTTP "
                    "(/mcp/tools/call) com o inner Twin Token — o tenant vem dos claims."
                ),
            }
        return [TextContent(type="text", text=json.dumps(payload, ensure_ascii=False, indent=2))]

    return server, settings, http_app


# ── Entry point ───────────────────────────────────────────────────────────────


async def _run() -> None:
    import uvicorn
    from mcp.server.stdio import stdio_server

    server, settings, http_app = build_server()
    cfg = uvicorn.Config(
        http_app,
        host="0.0.0.0",  # noqa: S104 — bind interno do container; ingress só via gateway (INV-1)
        port=settings.mcp_port,
        log_level="warning",
        access_log=False,
    )
    server_http = uvicorn.Server(cfg)
    try:
        async with stdio_server() as (read_stream, write_stream):
            await asyncio.gather(
                server.run(read_stream, write_stream, server.create_initialization_options()),
                server_http.serve(),
            )
    except (EOFError, BrokenPipeError):
        pass


def main() -> None:
    # MCP_HTTP_ONLY=1 → só o sidecar HTTP (uso típico atrás do gateway, sem stdio).
    if os.getenv("MCP_HTTP_ONLY", "0") == "1":
        import uvicorn

        _server, settings, http_app = build_server()
        uvicorn.run(http_app, host="0.0.0.0", port=settings.mcp_port, log_level="warning")  # noqa: S104
        return
    asyncio.run(_run())


if __name__ == "__main__":
    main()
