"""Servidor MCP do test — sidecar kind=mcp_http, GATEWAY-READY (Model C).

Reescrito para o padrão canônico do platform-service-template (v2.0). Implementa o
contrato de integração com o MCP Gateway central (platform-mcp-gateway):
  - docs/standards/STD-MCP-001-mcp-gateway-integration-contract.md  (CI-1..CI-11)
  - docs/standards/STD-SEC-006-token-model-c-inner-token.md          (inner token / audiência)

Pontos gateway-ready:
  1. /mcp/tools/list emite, por tool, inputSchema type=object + capability +
     required_scope + resource_type + data_domain (o gateway NÃO deriva por nome).
  2. /mcp/tools/call re-verifica o **inner Twin Token** (aud=mcp:test-mcp) via
     JWKS do platform-admin, na PRÓPRIA audiência (defense in depth — CI-4/CI-5). O
     inner token chega em params._meta.twin_token.
  3. tenant_id vem SEMPRE dos claims do token verificado — nunca de argumento do
     cliente (SEC-035 / INV-3). As tools de teste não o consomem (é só p/
     governança), então o dispatcher o remove antes de chamar a função.
  4. _EXEMPT_TOOLS (tokenless) e _EXCLUDE_TOOLS (denylist fail-safe).
  5. /docs desabilitado (DOCS_ENABLED=false — HTTP-01).

Transporte: stdio (primário, MCP) + sidecar HTTP (:MCP_PORT, default 7100):
  GET  /v1/health        — liveness (health_path do registro, sem token)
  GET  /mcp/tools/list   — catálogo governado (com metadados de policy)
  POST /mcp/tools/call   — execução (inner token obrigatório, exceto _EXEMPT_TOOLS)

NOTA: test-mcp persiste no PostgreSQL via ``TestStore`` (backend real, não
compute-only), então o dispatcher recebe o ``store`` e o injeta nas tools —
preservando a lógica original de src/tools/ (planos, cenários, checklists, bugs).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import jwt  # PyJWT — verificação RS256 do inner token via JWKS
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from mcp.server import Server
from mcp.types import TextContent, Tool

from ..config.logging import configure_logging
from ..config.settings import Settings, get_settings
from ..db.store import TestStore
from ..tools import checklist_tool, plan_tool, scenario_tool, validation_tool

_log = logging.getLogger(__name__)


class _JSONEncoder(json.JSONEncoder):
    """Serializa tipos extras do psycopg2 (datetime, date, Decimal)."""

    def default(self, o: Any) -> Any:
        if isinstance(o, (datetime, date)):
            return o.isoformat()
        if isinstance(o, Decimal):
            return float(o)
        return super().default(o)


# ── Tool Schemas + Policy metadata (STD-MCP-001 CI-2) ─────────────────────────
# Cada tool declara, além de description/schema, os 4 campos de política:
#   capability     — id estável <namespace>.<tool> (não derivar por nome no gateway)
#   required_scope — escopo de execução no formato dominio:tipo:acao (least-privilege)
#   resource_type  — tipo de recurso tocado
#   data_domain    — domínio de dado (governa HITL floor / classificação LGPD)
# inputSchema MUST ser type=object com properties (senão a validação no front-door
# é fail-open). Mutação → verbo :write; consulta → :read.
# ─────────────────────────────────────────────────────────────────────────────
_TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    # ── Plans ─────────────────────────────────────────────────────────────────
    "create_test_plan": {
        "description": (
            "Cria um plano de testes para uma feature ou endpoint. "
            "Retorna plan_id usado em todas as operações subsequentes."
        ),
        "capability": "test-mcp.create_test_plan",
        "required_scope": "test-mcp:plan:write",
        "resource_type": "plan",
        "data_domain": "quality",
        "schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Título do plano (ex: 'GET /api/users')"},
                "scope": {"type": "string", "description": "O que será testado e quais limites"},
                "feature": {"type": "string", "description": "Nome da feature ou ticket relacionado"},
            },
            "required": ["title", "scope"],
        },
    },
    "get_test_plan": {
        "description": "Retorna um plano de teste com métricas de cobertura, resultados e findings.",
        "capability": "test-mcp.get_test_plan",
        "required_scope": "test-mcp:plan:read",
        "resource_type": "plan",
        "data_domain": "quality",
        "schema": {
            "type": "object",
            "properties": {
                "plan_id": {"type": "string", "description": "ID do plano de teste"},
                "include_scenarios": {
                    "type": "boolean",
                    "description": "Incluir lista completa de cenários no retorno",
                },
            },
            "required": ["plan_id"],
        },
    },
    "list_test_plans": {
        "description": "Lista planos de teste, opcionalmente filtrados por status.",
        "capability": "test-mcp.list_test_plans",
        "required_scope": "test-mcp:plan:read",
        "resource_type": "plan",
        "data_domain": "quality",
        "schema": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "Filtrar por status",
                    "enum": ["active", "completed", "archived"],
                },
                "limit": {"type": "integer", "description": "Máximo de planos retornados (default 20)"},
            },
        },
    },
    # ── Scenarios ─────────────────────────────────────────────────────────────
    "generate_scenarios": {
        "description": (
            "Gera e salva automaticamente cenários de teste baseados em templates para a "
            "categoria informada. Categorias: rest_api, react_component, auth_flow, "
            "db_migration, websocket, form_validation, ui_data_validation."
        ),
        "capability": "test-mcp.generate_scenarios",
        "required_scope": "test-mcp:scenario:write",
        "resource_type": "scenario",
        "data_domain": "quality",
        "schema": {
            "type": "object",
            "properties": {
                "plan_id": {"type": "string", "description": "ID do plano de teste"},
                "category": {
                    "type": "string",
                    "description": "Categoria da feature",
                    "enum": [
                        "rest_api",
                        "react_component",
                        "auth_flow",
                        "db_migration",
                        "websocket",
                        "form_validation",
                        "ui_data_validation",
                    ],
                },
                "context": {
                    "type": "string",
                    "description": "Contexto específico (ex: '/api/users') para personalizar os cenários",
                },
            },
            "required": ["plan_id", "category"],
        },
    },
    "add_scenario": {
        "description": "Adiciona um cenário de teste específico e customizado ao plano.",
        "capability": "test-mcp.add_scenario",
        "required_scope": "test-mcp:scenario:write",
        "resource_type": "scenario",
        "data_domain": "quality",
        "schema": {
            "type": "object",
            "properties": {
                "plan_id": {"type": "string", "description": "ID do plano de teste"},
                "name": {"type": "string", "description": "Nome descritivo do cenário"},
                "category": {
                    "type": "string",
                    "enum": [
                        "happy_path",
                        "auth",
                        "boundary",
                        "error",
                        "edge_case",
                        "empty_state",
                        "pagination",
                        "performance",
                        "schema",
                        "concurrency",
                    ],
                },
                "steps": {"type": "string", "description": "Passos para executar o cenário"},
                "expected_result": {"type": "string", "description": "Resultado esperado"},
                "priority": {
                    "type": "string",
                    "enum": ["critical", "high", "medium", "low"],
                    "description": "Prioridade do cenário (default medium)",
                },
                "preconditions": {"type": "string", "description": "Pré-condições necessárias"},
            },
            "required": ["plan_id", "name", "category", "steps", "expected_result"],
        },
    },
    "record_result": {
        "description": "Registra o resultado da execução de um cenário de teste.",
        "capability": "test-mcp.record_result",
        "required_scope": "test-mcp:scenario:write",
        "resource_type": "scenario",
        "data_domain": "quality",
        "schema": {
            "type": "object",
            "properties": {
                "plan_id": {"type": "string", "description": "ID do plano de teste"},
                "scenario_id": {"type": "integer", "description": "ID numérico do cenário"},
                "status": {
                    "type": "string",
                    "enum": ["passed", "failed", "blocked", "skipped"],
                },
                "actual_result": {"type": "string", "description": "O que realmente aconteceu"},
                "notes": {"type": "string", "description": "Observações adicionais"},
                "evidence": {
                    "type": "string",
                    "description": "Link ou referência para evidência (screenshot, log, etc.)",
                },
            },
            "required": ["plan_id", "scenario_id", "status"],
        },
    },
    # ── Checklists ────────────────────────────────────────────────────────────
    "create_checklist": {
        "description": (
            "Cria um checklist de verificação a partir de template ou com itens customizados. "
            "Templates: pre_deploy, post_deploy, code_review, security, accessibility, data_integrity."
        ),
        "capability": "test-mcp.create_checklist",
        "required_scope": "test-mcp:checklist:write",
        "resource_type": "checklist",
        "data_domain": "quality",
        "schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Título do checklist"},
                "checklist_type": {
                    "type": "string",
                    "enum": [
                        "pre_deploy",
                        "post_deploy",
                        "code_review",
                        "security",
                        "accessibility",
                        "data_integrity",
                        "custom",
                    ],
                },
                "plan_id": {"type": "string", "description": "Associar ao plano de teste (opcional)"},
                "use_template": {
                    "type": "boolean",
                    "description": "Usar template padrão para o tipo informado (default true)",
                },
                "items": {
                    "type": "array",
                    "description": "Itens customizados (obrigatório quando use_template=false ou type='custom')",
                    "items": {
                        "type": "object",
                        "properties": {
                            "description": {"type": "string"},
                            "required": {"type": "boolean"},
                            "category": {"type": "string"},
                        },
                        "required": ["description"],
                    },
                },
            },
            "required": ["title", "checklist_type"],
        },
    },
    "run_checklist": {
        "description": (
            "Inicia uma execução (run) de um checklist. Retorna todos os itens a verificar com seus IDs."
        ),
        "capability": "test-mcp.run_checklist",
        "required_scope": "test-mcp:checklist:write",
        "resource_type": "checklist",
        "data_domain": "quality",
        "schema": {
            "type": "object",
            "properties": {
                "checklist_id": {"type": "string", "description": "ID do checklist"},
                "executor": {
                    "type": "string",
                    "description": "Nome ou identificador de quem está executando",
                },
            },
            "required": ["checklist_id"],
        },
    },
    "check_item": {
        "description": "Marca um item do checklist como passed, failed, na (não aplicável) ou blocked.",
        "capability": "test-mcp.check_item",
        "required_scope": "test-mcp:checklist:write",
        "resource_type": "checklist",
        "data_domain": "quality",
        "schema": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string", "description": "ID da execução do checklist"},
                "item_id": {"type": "integer", "description": "ID numérico do item"},
                "status": {"type": "string", "enum": ["passed", "failed", "na", "blocked"]},
                "notes": {"type": "string", "description": "Observação sobre o item"},
            },
            "required": ["run_id", "item_id", "status"],
        },
    },
    # ── Bugs ──────────────────────────────────────────────────────────────────
    "add_bug": {
        "description": (
            "Registra um BUG no banco vinculado a um plano de teste. USE ESTA TOOL sempre que "
            "encontrar um bug, erro, falha ou comportamento inesperado. Bugs críticos bloqueiam a "
            "aprovação do plano (double_check retorna BLOQUEADO). Severidades: critical (sistema "
            "inoperante) | high (funcionalidade quebrada) | medium (degradação) | low (cosmético)."
        ),
        "capability": "test-mcp.add_bug",
        "required_scope": "test-mcp:bug:write",
        "resource_type": "bug",
        "data_domain": "quality",
        "schema": {
            "type": "object",
            "properties": {
                "plan_id": {"type": "string", "description": "ID do plano de teste ao qual o bug pertence"},
                "severity": {
                    "type": "string",
                    "enum": ["critical", "high", "medium", "low"],
                    "description": "critical=sistema parado | high=funcionalidade quebrada | medium=degradação | low=cosmético",
                },
                "title": {"type": "string", "description": "Título curto e descritivo do bug"},
                "description": {
                    "type": "string",
                    "description": "Descrição detalhada: passos para reproduzir, esperado vs atual",
                },
                "evidence": {
                    "type": "string",
                    "description": "Log, screenshot, stack trace ou link para evidência",
                },
            },
            "required": ["plan_id", "severity", "title", "description"],
        },
    },
    # ── Validation ────────────────────────────────────────────────────────────
    "double_check": {
        "description": (
            "Executa verificação completa do plano: lista cenários não executados, falhas abertas e "
            "findings críticos. Retorna veredicto APROVADO ou BLOQUEADO."
        ),
        "capability": "test-mcp.double_check",
        "required_scope": "test-mcp:validation:read",
        "resource_type": "validation",
        "data_domain": "quality",
        "schema": {
            "type": "object",
            "properties": {"plan_id": {"type": "string", "description": "ID do plano de teste"}},
            "required": ["plan_id"],
        },
    },
    "get_validation_status": {
        "description": (
            "Retorna status completo de validação: cobertura %, pass rate %, findings por "
            "severidade, grade (A-F) e se está pronto para ship."
        ),
        "capability": "test-mcp.get_validation_status",
        "required_scope": "test-mcp:validation:read",
        "resource_type": "validation",
        "data_domain": "quality",
        "schema": {
            "type": "object",
            "properties": {"plan_id": {"type": "string", "description": "ID do plano de teste"}},
            "required": ["plan_id"],
        },
    },
}

# Tools encaminhadas SEM inner token (CI-7 exempt_tools — só tokenless). test-mcp
# não expõe tool pública/tokenless: TODA execução exige inner token válido.
_EXEMPT_TOOLS: frozenset[str] = frozenset()
# Denylist fail-safe: tools que NUNCA saem pelo gateway (CI-7).
_EXCLUDE_TOOLS: frozenset[str] = frozenset()

# Campos de policy repassados no /mcp/tools/list (o gateway lê estes campos).
_POLICY_FIELDS = ("capability", "required_scope", "resource_type", "data_domain")


# ── Verificação do inner Twin Token (STD-SEC-006 / CI-4/CI-5) ─────────────────


def _verify_inner_token(twin_token: str, settings: Settings) -> dict[str, Any]:
    """Re-verifica o inner Twin Token na PRÓPRIA audiência (mcp:test-mcp).

    O gateway já verificou o front token; o backend é 'one more verified client'
    (defense in depth). RS256 via JWKS do platform-admin; audiência exata; jti
    obrigatório. Levanta em qualquer falha (fail-closed).
    """
    if not settings.mcp_twin_audience or not settings.url_admin_twin_jwks:
        raise PermissionError(
            "integração com o gateway não configurada: defina MCP_TWIN_AUDIENCE "
            "(mcp:test-mcp) e URL_ADMIN_TWIN_JWKS (ver STD-SEC-006 / IT-006)."
        )
    signing_key = jwt.PyJWKClient(settings.url_admin_twin_jwks).get_signing_key_from_jwt(twin_token)
    return jwt.decode(
        twin_token,
        signing_key.key,
        algorithms=["RS256"],  # RS256 exclusivo (STD-SEC-001)
        audience=settings.mcp_twin_audience,  # a falha de integração nº 1
        options={"require": ["exp", "aud", "jti"]},  # sem jti → rejeita (JTI_REQUIRED)
    )


# ── Dispatcher (backend-backed: store injetado nas tools) ─────────────────────

_DISPATCH: dict[str, Callable[..., dict[str, Any]]] = {
    "create_test_plan": plan_tool.create_test_plan,
    "get_test_plan": plan_tool.get_test_plan,
    "list_test_plans": plan_tool.list_test_plans,
    "generate_scenarios": scenario_tool.generate_scenarios,
    "add_scenario": scenario_tool.add_scenario,
    "record_result": scenario_tool.record_result,
    "create_checklist": checklist_tool.create_checklist,
    "run_checklist": checklist_tool.run_checklist,
    "check_item": checklist_tool.check_item,
    "add_bug": validation_tool.add_finding,  # exposto como add_bug (persiste em bug_reports)
    "double_check": validation_tool.double_check,
    "get_validation_status": validation_tool.get_validation_status,
}


def _dispatch(name: str, args: dict[str, Any], store: TestStore) -> dict[str, Any]:
    """Despacha a chamada para a função de tool, preservando ``tool(store, **args)``.

    ``tenant_id`` é injetado pelo PEP nos args (INV-3) apenas para governança; as
    tools de teste não o consomem, então é removido antes da chamada.
    """
    func = _DISPATCH.get(name)
    if func is None:
        raise KeyError(name)
    call_args = {k: v for k, v in args.items() if k != "tenant_id"}
    try:
        return func(store, **call_args)
    except TypeError as exc:
        return {"error": "invalid_arguments", "message": str(exc), "tool": name}


def _serialize(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, cls=_JSONEncoder)


# ── HTTP Sidecar ──────────────────────────────────────────────────────────────


def _build_http_app(settings: Settings, store: TestStore) -> FastAPI:
    """Cria o sidecar HTTP (health + bridge governado /mcp/tools/*)."""
    app = FastAPI(
        title="test-mcp API",
        version="0.1.0",
        docs_url="/docs" if settings.docs_enabled else None,  # false em todo ambiente
        redoc_url=None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
    )

    @app.get("/v1/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "service": "test-mcp", "tools": len(_TOOL_SCHEMAS)}

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

    @app.post("/mcp/tools/call")
    def http_call_tool(body: dict) -> Any:
        params = body.get("params", body)
        name = params.get("name", "")
        arguments = dict(params.get("arguments", {}) or {})

        if name in _EXCLUDE_TOOLS:
            return JSONResponse(status_code=403, content={"error": "tool_excluded", "tool": name})

        # Execução (não-exempt) exige inner token válido; tenant vem dos claims.
        if name not in _EXEMPT_TOOLS:
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
            # SEC-035 / INV-3: tenant SEMPRE dos claims, nunca de argumento do cliente.
            arguments["tenant_id"] = tenant_id

        try:
            payload = _dispatch(name, arguments, store)
        except KeyError:
            return JSONResponse(status_code=404, content={"error": "unknown_tool", "tool": name})
        except Exception as exc:  # noqa: BLE001 — a resposta carrega o erro
            _log.exception("tool_internal_error: %s", name)
            payload = {"error": "internal_error", "detail": str(exc), "tool": name}
        content = [TextContent(type="text", text=_serialize(payload))]
        return {"result": {"content": [c.model_dump(exclude_none=True) for c in content]}}

    return app


# ── Server (stdio + sidecar) ──────────────────────────────────────────────────


def build_server() -> tuple[Any, Settings, TestStore, FastAPI]:
    """Inicializa o MCP Server (stdio), settings, o store e o sidecar HTTP."""
    settings = get_settings()
    settings.enforce_security_invariants()  # fail-fast (STD-SEC-001/004/006)
    configure_logging(settings)  # logs estruturados JSON (STD-OBS-001)
    store = TestStore(settings=settings)
    http_app = _build_http_app(settings, store)
    _log.info("test_mcp_ready tools=%d", len(_TOOL_SCHEMAS))

    server: Server = Server("test-mcp-server")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(name=name, description=meta["description"], inputSchema=meta["schema"])
            for name, meta in _TOOL_SCHEMAS.items()
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any] | None) -> list[TextContent]:
        args = arguments or {}
        try:
            payload = _dispatch(name, args, store)
        except KeyError:
            payload = {"error": "unknown_tool", "tool": name}
        except Exception as exc:  # noqa: BLE001
            payload = {"error": "internal_error", "detail": str(exc), "tool": name}
            _log.exception("tool_internal_error: %s", name)
        return [TextContent(type="text", text=_serialize(payload))]

    return server, settings, store, http_app


# ── Entry point ───────────────────────────────────────────────────────────────


async def _run() -> None:
    import uvicorn
    from mcp.server.stdio import stdio_server

    server, settings, _store, http_app = build_server()
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

        _server, settings, _store, http_app = build_server()
        uvicorn.run(http_app, host="0.0.0.0", port=settings.mcp_port, log_level="warning")  # noqa: S104
        return
    asyncio.run(_run())


if __name__ == "__main__":
    main()
