"""Test MCP Server — entry point e definição das tools MCP."""

from __future__ import annotations

import asyncio
import json
import logging

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from ..config.settings import TestSettings, get_settings
from ..db.store import TestStore
from ..tools import checklist_tool, plan_tool, scenario_tool, validation_tool

logger = logging.getLogger(__name__)


def build_server() -> tuple[Server, TestSettings, TestStore]:
    settings = get_settings()
    store = TestStore(settings.db_path)
    server = Server("test-mcp-server")

    # ── Tool definitions ───────────────────────────────────────────────────── #

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            # ── Plans ──────────────────────────────────────────────────────── #
            Tool(
                name="create_test_plan",
                description=(
                    "Cria um plano de testes para uma feature ou endpoint. "
                    "Retorna plan_id usado em todas as operações subsequentes."
                ),
                inputSchema={
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["title", "scope"],
                    "properties": {
                        "title": {"type": "string", "description": "Título do plano (ex: 'GET /api/users')"},
                        "scope": {"type": "string", "description": "O que será testado e quais limites"},
                        "feature": {"type": "string", "description": "Nome da feature ou ticket relacionado"},
                    },
                },
            ),
            Tool(
                name="get_test_plan",
                description="Retorna um plano de teste com métricas de cobertura, resultados e findings.",
                inputSchema={
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["plan_id"],
                    "properties": {
                        "plan_id": {"type": "string"},
                        "include_scenarios": {
                            "type": "boolean",
                            "default": False,
                            "description": "Incluir lista completa de cenários no retorno",
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
            # ── Scenarios ──────────────────────────────────────────────────── #
            Tool(
                name="generate_scenarios",
                description=(
                    "Gera e salva automaticamente cenários de teste baseados em templates para a categoria informada. "
                    "Categorias disponíveis: rest_api, react_component, auth_flow, db_migration, websocket, form_validation."
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
                            "description": "Contexto específico (ex: '/api/users') para personalizar os cenários gerados",
                        },
                    },
                },
            ),
            Tool(
                name="add_scenario",
                description="Adiciona um cenário de teste específico e customizado ao plano.",
                inputSchema={
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["plan_id", "name", "category", "steps", "expected_result"],
                    "properties": {
                        "plan_id": {"type": "string"},
                        "name": {"type": "string", "description": "Nome descritivo do cenário"},
                        "category": {
                            "type": "string",
                            "enum": [
                                "happy_path", "auth", "boundary", "error", "edge_case",
                                "empty_state", "pagination", "performance", "schema",
                                "concurrency",
                            ],
                        },
                        "steps": {"type": "string", "description": "Passos para executar o cenário"},
                        "expected_result": {"type": "string", "description": "Resultado esperado"},
                        "priority": {
                            "type": "string",
                            "enum": ["critical", "high", "medium", "low"],
                            "default": "medium",
                        },
                        "preconditions": {"type": "string", "description": "Pré-condições necessárias"},
                    },
                },
            ),
            Tool(
                name="record_result",
                description="Registra o resultado da execução de um cenário de teste.",
                inputSchema={
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["plan_id", "scenario_id", "status"],
                    "properties": {
                        "plan_id": {"type": "string"},
                        "scenario_id": {"type": "integer", "description": "ID numérico do cenário"},
                        "status": {
                            "type": "string",
                            "enum": ["passed", "failed", "blocked", "skipped"],
                        },
                        "actual_result": {"type": "string", "description": "O que realmente aconteceu"},
                        "notes": {"type": "string", "description": "Observações adicionais"},
                        "evidence": {"type": "string", "description": "Link ou referência para evidência (screenshot, log, etc.)"},
                    },
                },
            ),
            # ── Checklists ─────────────────────────────────────────────────── #
            Tool(
                name="create_checklist",
                description=(
                    "Cria um checklist de verificação a partir de template ou com itens customizados. "
                    "Templates disponíveis: pre_deploy, post_deploy, code_review, security, accessibility."
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
                            "description": "Usar template padrão para o tipo informado",
                        },
                        "items": {
                            "type": "array",
                            "description": "Itens customizados (obrigatório quando use_template=false ou type='custom')",
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
                description="Inicia uma execução (run) de um checklist. Retorna todos os itens a verificar com seus IDs.",
                inputSchema={
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["checklist_id"],
                    "properties": {
                        "checklist_id": {"type": "string"},
                        "executor": {"type": "string", "description": "Nome ou identificador de quem está executando"},
                    },
                },
            ),
            Tool(
                name="check_item",
                description="Marca um item do checklist como passed, failed, na (não aplicável) ou blocked.",
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
                        "notes": {"type": "string", "description": "Observação sobre o item"},
                    },
                },
            ),
            # ── Validation ─────────────────────────────────────────────────── #
            Tool(
                name="add_finding",
                description=(
                    "Registra um bug, problema ou risco encontrado durante os testes. "
                    "Findings críticos bloqueiam a aprovação do plano."
                ),
                inputSchema={
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["plan_id", "severity", "title", "description"],
                    "properties": {
                        "plan_id": {"type": "string"},
                        "severity": {
                            "type": "string",
                            "enum": ["critical", "high", "medium", "low"],
                        },
                        "title": {"type": "string", "description": "Título curto do finding"},
                        "description": {"type": "string", "description": "Descrição detalhada do problema"},
                        "evidence": {"type": "string", "description": "Link ou referência para evidência"},
                    },
                },
            ),
            Tool(
                name="double_check",
                description=(
                    "Executa verificação completa do plano: lista cenários não executados, "
                    "falhas abertas e findings críticos. Retorna veredicto APROVADO ou BLOQUEADO."
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
                    "Retorna status completo de validação: cobertura %, pass rate %, "
                    "findings por severidade, grade (A-F) e se está pronto para ship."
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

    # ── Tool handlers ──────────────────────────────────────────────────────── #

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
                case "add_finding":
                    result = validation_tool.add_finding(store, **arguments)
                case "double_check":
                    result = validation_tool.double_check(store, **arguments)
                case "get_validation_status":
                    result = validation_tool.get_validation_status(store, **arguments)
                case _:
                    result = {"error": "UnknownTool", "details": f"Tool '{name}' não existe"}

        except Exception as exc:
            logger.exception("Erro na tool %s", name)
            result = {"error": type(exc).__name__, "details": str(exc)}

        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

    return server, settings, store


async def _run() -> None:
    server, _settings, _store = build_server()
    logger.info("test_mcp_ready")
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    asyncio.run(_run())


if __name__ == "__main__":
    main()
