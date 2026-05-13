"""Test MCP Server â€” entry point e definiÃ§Ã£o das tools MCP."""

from __future__ import annotations

import os

import asyncio
import json
import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from fastapi import FastAPI
from mcp.server import Server
from mcp.types import TextContent, Tool

from ..config.settings import TestSettings, get_settings
from ..db.store import TestStore
from ..tools import checklist_tool, plan_tool, scenario_tool, validation_tool

logger = logging.getLogger(__name__)


class _JSONEncoder(json.JSONEncoder):
    """Serializa tipos extras do psycopg2 (datetime, Decimal)."""
    def default(self, o: Any) -> Any:
        if isinstance(o, (datetime, date)):
            return o.isoformat()
        if isinstance(o, Decimal):
            return float(o)
        return super().default(o)


def _build_http_app() -> FastAPI:
    app = FastAPI(title="Test API", version="0.1.0", docs_url="/docs")

    @app.get("/v1/health")
    def health() -> dict:
        return {"status": "ok", "service": "test-mcp"}

    return app


def build_server() -> tuple[Any, ...]:
    settings = get_settings()
    http_app = _build_http_app()
    store = TestStore(settings=settings)
    server = Server("test-mcp-server")

    # â”€â”€ Tool definitions â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ #

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            # â”€â”€ Plans â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ #
            Tool(
                name="create_test_plan",
                description=(
                    "Cria um plano de testes para uma feature ou endpoint. "
                    "Retorna plan_id usado em todas as operaÃ§Ãµes subsequentes."
                ),
                inputSchema={
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["title", "scope"],
                    "properties": {
                        "title": {"type": "string", "description": "TÃ­tulo do plano (ex: 'GET /api/users')"},
                        "scope": {"type": "string", "description": "O que serÃ¡ testado e quais limites"},
                        "feature": {"type": "string", "description": "Nome da feature ou ticket relacionado"},
                    },
                },
            ),
            Tool(
                name="get_test_plan",
                description="Retorna um plano de teste com mÃ©tricas de cobertura, resultados e findings.",
                inputSchema={
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["plan_id"],
                    "properties": {
                        "plan_id": {"type": "string"},
                        "include_scenarios": {
                            "type": "boolean",
                            "default": False,
                            "description": "Incluir lista completa de cenÃ¡rios no retorno",
                        },
                    },
                },
            ),
            Tool(
                name="list_test_plans",
                description="Lista planos de teste, opcionalmente filtrados por status.",
                inputSchema={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "status": {
                            "type": "string",
                            "enum": ["active", "completed", "archived"],
                            "description": "Filtrar por status",
                        },
                        "limit": {"type": "integer", "default": 20},
                    },
                },
            ),
            # â”€â”€ Scenarios â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ #
            Tool(
                name="generate_scenarios",
                description=(
                    "Gera e salva automaticamente cenÃ¡rios de teste baseados em templates para a categoria informada. "
                    "Categorias disponÃ­veis: rest_api, react_component, auth_flow, db_migration, websocket, form_validation."
                ),
                inputSchema={
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["plan_id", "category"],
                    "properties": {
                        "plan_id": {"type": "string"},
                        "category": {
                            "type": "string",
                            "enum": ["rest_api", "react_component", "auth_flow", "db_migration", "websocket", "form_validation", "ui_data_validation"],
                        },
                        "context": {
                            "type": "string",
                            "description": "Contexto especÃ­fico (ex: '/api/users') para personalizar os cenÃ¡rios gerados",
                        },
                    },
                },
            ),
            Tool(
                name="add_scenario",
                description="Adiciona um cenÃ¡rio de teste especÃ­fico e customizado ao plano.",
                inputSchema={
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["plan_id", "name", "category", "steps", "expected_result"],
                    "properties": {
                        "plan_id": {"type": "string"},
                        "name": {"type": "string", "description": "Nome descritivo do cenÃ¡rio"},
                        "category": {
                            "type": "string",
                            "enum": [
                                "happy_path", "auth", "boundary", "error", "edge_case",
                                "empty_state", "pagination", "performance", "schema",
                                "concurrency",
                            ],
                        },
                        "steps": {"type": "string", "description": "Passos para executar o cenÃ¡rio"},
                        "expected_result": {"type": "string", "description": "Resultado esperado"},
                        "priority": {
                            "type": "string",
                            "enum": ["critical", "high", "medium", "low"],
                            "default": "medium",
                        },
                        "preconditions": {"type": "string", "description": "PrÃ©-condiÃ§Ãµes necessÃ¡rias"},
                    },
                },
            ),
            Tool(
                name="record_result",
                description="Registra o resultado da execuÃ§Ã£o de um cenÃ¡rio de teste.",
                inputSchema={
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["plan_id", "scenario_id", "status"],
                    "properties": {
                        "plan_id": {"type": "string"},
                        "scenario_id": {"type": "integer", "description": "ID numÃ©rico do cenÃ¡rio"},
                        "status": {
                            "type": "string",
                            "enum": ["passed", "failed", "blocked", "skipped"],
                        },
                        "actual_result": {"type": "string", "description": "O que realmente aconteceu"},
                        "notes": {"type": "string", "description": "ObservaÃ§Ãµes adicionais"},
                        "evidence": {"type": "string", "description": "Link ou referÃªncia para evidÃªncia (screenshot, log, etc.)"},
                    },
                },
            ),
            # â”€â”€ Checklists â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ #
            Tool(
                name="create_checklist",
                description=(
                    "Cria um checklist de verificaÃ§Ã£o a partir de template ou com itens customizados. "
                    "Templates disponÃ­veis: pre_deploy, post_deploy, code_review, security, accessibility."
                ),
                inputSchema={
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["title", "checklist_type"],
                    "properties": {
                        "title": {"type": "string"},
                        "checklist_type": {
                            "type": "string",
                            "enum": ["pre_deploy", "post_deploy", "code_review", "security", "accessibility", "data_integrity", "custom"],
                        },
                        "plan_id": {"type": "string", "description": "Associar ao plano de teste (opcional)"},
                        "use_template": {
                            "type": "boolean",
                            "default": True,
                            "description": "Usar template padrÃ£o para o tipo informado",
                        },
                        "items": {
                            "type": "array",
                            "description": "Itens customizados (obrigatÃ³rio quando use_template=false ou type='custom')",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "description": {"type": "string"},
                                    "required": {"type": "boolean", "default": True},
                                    "category": {"type": "string"},
                                },
                                "required": ["description"],
                            },
                        },
                    },
                },
            ),
            Tool(
                name="run_checklist",
                description="Inicia uma execuÃ§Ã£o (run) de um checklist. Retorna todos os itens a verificar com seus IDs.",
                inputSchema={
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["checklist_id"],
                    "properties": {
                        "checklist_id": {"type": "string"},
                        "executor": {"type": "string", "description": "Nome ou identificador de quem estÃ¡ executando"},
                    },
                },
            ),
            Tool(
                name="check_item",
                description="Marca um item do checklist como passed, failed, na (nÃ£o aplicÃ¡vel) ou blocked.",
                inputSchema={
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["run_id", "item_id", "status"],
                    "properties": {
                        "run_id": {"type": "string"},
                        "item_id": {"type": "integer"},
                        "status": {
                            "type": "string",
                            "enum": ["passed", "failed", "na", "blocked"],
                        },
                        "notes": {"type": "string", "description": "ObservaÃ§Ã£o sobre o item"},
                    },
                },
            ),
            # â”€â”€ Bugs â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ #
            Tool(
                name="add_bug",
                description=(
                    "Registra um BUG no banco de dados vinculado a um plano de teste. "
                    "USE ESTA TOOL sempre que encontrar um bug, erro, falha ou comportamento inesperado â€” "
                    "NÃƒO use add_artifact para bugs. "
                    "Bugs crÃ­ticos bloqueiam a aprovaÃ§Ã£o do plano (double_check retorna BLOQUEADO). "
                    "Severidades: critical (sistema inoperante) | high (funcionalidade quebrada) | "
                    "medium (degradaÃ§Ã£o parcial) | low (cosmÃ©tico/menor)."
                ),
                inputSchema={
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["plan_id", "severity", "title", "description"],
                    "properties": {
                        "plan_id": {"type": "string", "description": "ID do plano de teste ao qual o bug pertence."},
                        "severity": {
                            "type": "string",
                            "enum": ["critical", "high", "medium", "low"],
                            "description": "critical=sistema parado | high=funcionalidade quebrada | medium=degradaÃ§Ã£o | low=cosmÃ©tico",
                        },
                        "title": {"type": "string", "description": "TÃ­tulo curto e descritivo do bug (ex: 'Login falha com email maiÃºsculo')"},
                        "description": {"type": "string", "description": "DescriÃ§Ã£o detalhada: passos para reproduzir, comportamento esperado vs atual."},
                        "evidence": {"type": "string", "description": "Log, screenshot, stack trace ou link para evidÃªncia."},
                    },
                },
            ),
            Tool(
                name="double_check",
                description=(
                    "Executa verificaÃ§Ã£o completa do plano: lista cenÃ¡rios nÃ£o executados, "
                    "falhas abertas e findings crÃ­ticos. Retorna veredicto APROVADO ou BLOQUEADO."
                ),
                inputSchema={
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["plan_id"],
                    "properties": {
                        "plan_id": {"type": "string"},
                    },
                },
            ),
            Tool(
                name="get_validation_status",
                description=(
                    "Retorna status completo de validaÃ§Ã£o: cobertura %, pass rate %, "
                    "findings por severidade, grade (A-F) e se estÃ¡ pronto para ship."
                ),
                inputSchema={
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["plan_id"],
                    "properties": {
                        "plan_id": {"type": "string"},
                    },
                },
            ),
        ]

    # â”€â”€ Tool handlers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ #

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        try:
            match name:
                # Plans
                case "create_test_plan":
                    result = plan_tool.create_test_plan(store, **arguments)
                case "get_test_plan":
                    result = plan_tool.get_test_plan(store, **arguments)
                case "list_test_plans":
                    result = plan_tool.list_test_plans(store, **arguments)
                # Scenarios
                case "generate_scenarios":
                    result = scenario_tool.generate_scenarios(store, **arguments)
                case "add_scenario":
                    result = scenario_tool.add_scenario(store, **arguments)
                case "record_result":
                    result = scenario_tool.record_result(store, **arguments)
                # Checklists
                case "create_checklist":
                    result = checklist_tool.create_checklist(store, **arguments)
                case "run_checklist":
                    result = checklist_tool.run_checklist(store, **arguments)
                case "check_item":
                    result = checklist_tool.check_item(store, **arguments)
                # Validation
                case "add_bug" | "add_finding":  # add_finding mantido por compatibilidade
                    result = validation_tool.add_finding(store, **arguments)
                case "double_check":
                    result = validation_tool.double_check(store, **arguments)
                case "get_validation_status":
                    result = validation_tool.get_validation_status(store, **arguments)
                case _:
                    result = {"error": "UnknownTool", "details": f"Tool '{name}' nÃ£o existe"}

        except Exception as exc:
            logger.exception("Erro na tool %s", name)
            result = {"error": type(exc).__name__, "details": str(exc)}

        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2, cls=_JSONEncoder))]

    @http_app.get("/mcp/tools/list")
    async def http_list_tools() -> dict:
        tools = await list_tools()
        return {"result": {"tools": [t.model_dump(exclude_none=True) for t in tools]}}

    @http_app.post("/mcp/tools/call")
    async def http_call_tool(body: dict) -> dict:
        params = body.get("params", body)
        result = await call_tool(params.get("name", ""), params.get("arguments", {}))
        return {"result": {"content": [r.model_dump(exclude_none=True) for r in result]}}

    return server, settings, store, http_app

async def _run() -> None:
    import uvicorn
    from mcp.server.stdio import stdio_server

    server, *rest = build_server()
    http_app = rest[-1]

    cfg = uvicorn.Config(
        http_app, host="0.0.0.0", port=int(os.getenv("MCP_PORT", "7100")),
        log_level="warning", access_log=False,
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
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    asyncio.run(_run())


if __name__ == "__main__":
    main()
