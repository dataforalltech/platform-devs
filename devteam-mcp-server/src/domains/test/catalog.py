"""Catálogo de tools + dispatcher do domínio *test* (consolidado no devteam-mcp).

Este módulo é a fatia "de negócio" do antigo `test-mcp-server/src/server/mcp_server.py`:
mantém intactos o ``_TOOL_SCHEMAS`` (metadados de policy por tool) e o ``dispatch``
(roteamento op → handler via ``_DISPATCH``). O que ficou de FORA é o boot/serve/segurança
(FastAPI, PEP inner-token, stdio, tenant plumbing, serialização) — isso é responsabilidade
do AGREGADOR (`src/server/mcp_server.py`), compartilhado por todos os domínios.

Diferenças vs. o server-fonte (strangler — fiel, sem inventar comportamento):
  * ``capability`` passa a ``devteam-mcp.test_<op>`` (namespace do server consolidado +
    nome de tool já prefixado pelo domínio — o gateway não deriva por nome).
  * ``required_scope`` passa a ``test:<recurso>:<ação>`` — PRESERVA o least-privilege
    por-tool do domínio (data_domain=quality), só troca o antigo prefixo de namespace
    ``test-mcp`` pelo domínio canônico ``test``.
  * As CHAVES de ``_TOOL_SCHEMAS`` aqui continuam os nomes de op SEM prefixo
    (``create_test_plan``); o ``plugin.register()`` prefixa (``test_create_test_plan``) e o
    ``plugin.dispatch`` retira o prefixo antes de chamar ``dispatch`` daqui — assim a lógica
    de roteamento copiada do server-fonte fica byte-a-byte idêntica.

O ``_SOURCE_SCHEMAS`` abaixo é o ``_TOOL_SCHEMAS`` do server-fonte transcrito byte-a-byte
(descrições/schemas/resource_type/data_domain inalterados); ``_relabel`` reescreve APENAS
``capability`` e ``required_scope`` para o namespace consolidado (via ``DOMAIN``).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from .db.store import TestStore
from .tools import checklist_tool, plan_tool, scenario_tool, validation_tool

# Domínio canônico deste plugin — usado no capability/required_scope e como prefixo de
# tool (o agregador descobre o domínio por ``<domain>_<op>``).
DOMAIN = "test"


# ── Tool Schemas + Policy metadata (STD-MCP-001 CI-2) ─────────────────────────
# Cada tool declara, além de description/schema, os 4 campos de política:
#   capability     — id estável <namespace>.<tool> (não derivar por nome no gateway)
#   required_scope — escopo de execução no formato dominio:tipo:acao (least-privilege)
#   resource_type  — tipo de recurso tocado
#   data_domain    — domínio de dado (governa HITL floor / classificação LGPD)
# inputSchema MUST ser type=object com properties (senão a validação no front-door
# é fail-open). Mutação → verbo :write; consulta → :read.
# ─────────────────────────────────────────────────────────────────────────────
_SOURCE_SCHEMAS: dict[str, dict[str, Any]] = {
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


def _relabel(op: str, meta: dict[str, Any]) -> dict[str, Any]:
    """Reescreve SÓ ``capability``/``required_scope`` p/ o namespace consolidado.

    ``capability`` = ``devteam-mcp.<domínio>_<op>`` (id estável já prefixado pelo domínio);
    ``required_scope`` = ``<domínio>:<recurso>:<ação>`` — troca só o antigo prefixo de
    namespace ``test-mcp`` pelo domínio canônico ``test``, preservando o least-privilege
    por-tool (a "cauda" ``<recurso>:<ação>`` vem intacta do server-fonte). Os demais campos
    (description, resource_type, data_domain, schema) ficam inalterados.
    """
    return {
        **meta,
        "capability": f"devteam-mcp.{DOMAIN}_{op}",
        "required_scope": f"{DOMAIN}:{meta['required_scope'].split(':', 1)[1]}",
    }


_TOOL_SCHEMAS: dict[str, dict[str, Any]] = {op: _relabel(op, meta) for op, meta in _SOURCE_SCHEMAS.items()}


# ── Dispatcher (backend-backed: store tenant-scoped injetado nas tools) ────────

_DISPATCH: dict[str, Callable[..., Awaitable[dict[str, Any]]]] = {
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


async def dispatch(name: str, args: dict[str, Any], store: TestStore) -> dict[str, Any]:
    """Despacha a chamada para a função de tool async, preservando ``tool(store, **args)``.

    ``name`` é o nome de op SEM prefixo de domínio (o ``plugin.dispatch`` já o retirou). O
    tenant NÃO viaja nos args (INV-3): o ``store`` já está ligado ao pool do tenant
    (resolvido dos claims do inner token), então o tenant dirige o pool, não a chamada.
    """
    func = _DISPATCH.get(name)
    if func is None:
        raise KeyError(name)
    try:
        return await func(store, **args)
    except TypeError as exc:
        return {"error": "invalid_arguments", "message": str(exc), "tool": name}
