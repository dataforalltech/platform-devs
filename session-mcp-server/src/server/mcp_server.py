"""Servidor MCP Session — gerenciamento de sessões e tarefas de trabalho Claude Code.

Modo híbrido: stdio (para Claude/registry) + HTTP (para gateway e cross-MCP) na porta 7100.
"""
from __future__ import annotations

import os

import asyncio
import json
from typing import Any

from fastapi import FastAPI
from mcp.types import TextContent, Tool

from ..config.settings import SessionSettings, get_settings
from ..db.store import (
    ACTOR_TYPES,
    SUGGESTION_KINDS,
    SUGGESTION_PRIORITIES,
    SUGGESTION_STATUSES,
    TASK_STATUSES,
    SessionStore,
)
from ..tools.session_tool import (
    accept_suggestion,
    add_artifact,
    add_service_dependency,
    add_task,
    approve_task,
    cancel_task,
    complete_task,
    confirm_branch_created,
    defer_suggestion,
    end_session,
    fail_task,
    get_decision_tool,
    get_session,
    get_suggestion_tool,
    get_task,
    list_decisions_tool,
    list_service_dependencies,
    list_sessions,
    list_suggestions_tool,
    list_tasks,
    reject_suggestion,
    remove_service_dependency,
    resume_session,
    save_checkpoint,
    start_session,
    start_task,
    submit_suggestion,
    supersede_suggestion,
    update_session,
)

_ACTOR_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "description": "Quem tomou a decisão (governança).",
    "properties": {
        "type": {"type": "string", "enum": list(ACTOR_TYPES)},
        "id": {
            "type": "string",
            "description": "Email do humano, session_id do agente, ou nome do sistema.",
        },
    },
    "required": ["type", "id"],
}

# ---------------------------------------------------------------------- #
# Schemas                                                                 #
# ---------------------------------------------------------------------- #
_TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "start_session": {
        "description": (
            "Registra nova sessão. Devolve branch_name sugerido e next_action para criar via deploy-mcp. "
            "'repo' obrigatório; 'base_branch' default: develop."
        ),
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Título curto da sessão (ex: 'Refactor auth JWT')",
                },
                "objective": {
                    "type": "string",
                    "description": "Objetivo detalhado do que será feito nesta sessão",
                },
                "repo": {
                    "type": "string",
                    "description": "Repositório DONO da sessão (obrigatório).",
                },
                "base_branch": {
                    "type": "string",
                    "description": "Branch base (default: develop) — usada como from_ref ao criar a branch da sessão.",
                },
            },
            "required": ["title", "objective", "repo"],
        },
    },
    "confirm_branch_created": {
        "description": (
            "Confirma que a branch da sessão foi criada via deploy-mcp.create_branch. "
            "sha base opcional (auditoria)."
        ),
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "session_id": {"type": "string", "description": "ID da sessão"},
                "sha": {
                    "type": "string",
                    "description": "Sha base da branch (retornado por deploy-mcp.create_branch).",
                },
            },
            "required": ["session_id"],
        },
    },
    "save_checkpoint": {
        "description": (
            "Salva snapshot do progresso. Use ao concluir etapas ou antes do contexto esgotar. "
            "context aceita JSON com estado de retomada."
        ),
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "session_id": {"type": "string", "description": "ID da sessão (ex: sess_abc123)"},
                "summary": {
                    "type": "string",
                    "description": "Resumo do estado atual — o que foi feito e o que falta",
                },
                "context": {
                    "type": "object",
                    "description": "Contexto estruturado opcional (arquivos pendentes, decisões, próximos passos)",
                },
            },
            "required": ["session_id", "summary"],
        },
    },
    "update_session": {
        "description": (
            "Atualiza o status e/ou progresso de uma sessão. "
            "Status: active | paused | completed."
        ),
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "session_id": {"type": "string"},
                "status": {
                    "type": "string",
                    "enum": ["active", "paused", "completed"],
                    "description": "Novo status da sessão",
                },
                "progress": {
                    "type": "string",
                    "description": "Texto livre descrevendo o progresso atual",
                },
            },
            "required": ["session_id"],
        },
    },
    "add_artifact": {
        "description": (
            "Registra um artefato ou evento relevante na sessão. "
            "Tipos: file_changed, file_created, file_deleted, decision, tool_call, error, note."
        ),
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "session_id": {"type": "string"},
                "artifact_type": {
                    "type": "string",
                    "enum": [
                        "file_changed",
                        "file_created",
                        "file_deleted",
                        "decision",
                        "tool_call",
                        "error",
                        "note",
                    ],
                    "description": "Tipo do artefato",
                },
                "content": {
                    "type": "string",
                    "description": "Conteúdo do artefato (caminho do arquivo, descrição da decisão, etc.)",
                },
            },
            "required": ["session_id", "artifact_type", "content"],
        },
    },
    "list_sessions": {
        "description": (
            "Lista sessões recentes. "
            "Filtre por status (active/paused/completed) ou repo para ver sessões em andamento."
        ),
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["active", "paused", "completed"],
                    "description": "Filtrar por status",
                },
                "repo": {
                    "type": "string",
                    "description": "Filtrar por nome/caminho do repo (busca parcial)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Máximo de sessões a retornar (default: 20)",
                    "default": 20,
                },
            },
            "required": [],
        },
    },
    "get_session": {
        "description": (
            "Retorna dados completos de uma sessão: "
            "metadados, último checkpoint e contagem de artefatos."
        ),
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "session_id": {"type": "string", "description": "ID da sessão"},
            },
            "required": ["session_id"],
        },
    },
    "resume_session": {
        "description": (
            "Retorna contexto completo para retomada: checkpoints, artefatos recentes e hint. "
            "Reativa sessões pausadas."
        ),
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "session_id": {"type": "string", "description": "ID da sessão a retomar"},
            },
            "required": ["session_id"],
        },
    },
    "end_session": {
        "description": (
            "Encerra sessão como completed. Falha se houver tarefas abertas. "
            "actor + rationale obrigatórios."
        ),
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "session_id": {"type": "string"},
                "actor": _ACTOR_SCHEMA,
                "rationale": {
                    "type": "string",
                    "description": "Por que a sessão está sendo encerrada (obrigatório).",
                },
                "final_summary": {
                    "type": "string",
                    "description": "Resumo final do que foi realizado na sessão",
                },
            },
            "required": ["session_id", "actor", "rationale"],
        },
    },
    "add_task": {
        "description": (
            "Cria tarefa na sessão (single ou bulk). "
            "needs_human_decision=true bloqueia start_task até approve_task."
        ),
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "session_id": {"type": "string", "description": "ID da sessão"},
                "title": {"type": "string", "description": "Título da tarefa (modo single)"},
                "description": {
                    "type": "string",
                    "description": "Descrição opcional da tarefa (modo single)",
                },
                "needs_human_decision": {
                    "type": "boolean",
                    "description": "Se true, start_task fica bloqueado até approve_task. Default false.",
                    "default": False,
                },
                "tasks": {
                    "type": "array",
                    "description": "Lista de tarefas a criar em lote (modo bulk)",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "title": {"type": "string"},
                            "description": {"type": "string"},
                            "needs_human_decision": {"type": "boolean"},
                        },
                        "required": ["title"],
                    },
                },
            },
            "required": ["session_id"],
        },
    },
    "approve_task": {
        "description": (
            "Decisão sobre task com needs_human_decision=true. "
            "go = libera start_task; no_go = cancela. actor obrigatório."
        ),
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "task_id": {"type": "integer"},
                "decision": {
                    "type": "string",
                    "enum": ["go", "no_go"],
                    "description": "go = aprova, no_go = rejeita (cancela a task).",
                },
                "actor": _ACTOR_SCHEMA,
                "rationale": {
                    "type": "string",
                    "description": "Por que esta decisão (obrigatório para no_go).",
                },
                "notes": {
                    "type": "string",
                    "description": "Texto adicional gravado em decision_notes da task.",
                },
            },
            "required": ["task_id", "decision", "actor"],
        },
    },
    "start_task": {
        "description": "Marca uma tarefa como 'in_progress'. Só funciona a partir de 'pending'.",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "task_id": {"type": "integer", "description": "ID da tarefa"},
            },
            "required": ["task_id"],
        },
    },
    "complete_task": {
        "description": (
            "Marca tarefa como concluída. Requer commit_sha + commit_message "
            "do deploy-mcp.commit_files chamado ANTES desta tool."
        ),
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "task_id": {"type": "integer", "description": "ID da tarefa"},
                "commit_sha": {
                    "type": "string",
                    "description": "Sha do commit retornado por mcp__deploy-mcp__commit_files.",
                },
                "commit_message": {
                    "type": "string",
                    "description": "Mensagem do commit (a mesma usada no commit_files).",
                },
                "result": {
                    "type": "string",
                    "description": "Notas livres sobre o resultado (campo informativo).",
                },
            },
            "required": ["task_id", "commit_sha", "commit_message"],
        },
    },
    "fail_task": {
        "description": (
            "Marca uma tarefa como 'failed' registrando o motivo. "
            "actor obrigatório (governança); reason obrigatório."
        ),
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "task_id": {"type": "integer"},
                "actor": _ACTOR_SCHEMA,
                "reason": {"type": "string", "description": "Motivo da falha"},
            },
            "required": ["task_id", "actor", "reason"],
        },
    },
    "cancel_task": {
        "description": (
            "Cancela uma tarefa (de 'pending' ou 'in_progress'). "
            "actor + reason obrigatórios (governança)."
        ),
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "task_id": {"type": "integer"},
                "actor": _ACTOR_SCHEMA,
                "reason": {"type": "string", "description": "Motivo do cancelamento"},
            },
            "required": ["task_id", "actor", "reason"],
        },
    },
    "list_tasks": {
        "description": (
            "Lista as tarefas de uma sessão, opcionalmente filtrando por status. "
            "Estados possíveis: pending | in_progress | completed | failed | cancelled."
        ),
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "session_id": {"type": "string", "description": "ID da sessão"},
                "status": {
                    "type": "string",
                    "enum": list(TASK_STATUSES),
                    "description": "Filtrar por status",
                },
            },
            "required": ["session_id"],
        },
    },
    "get_task": {
        "description": "Retorna os dados completos de uma tarefa pelo ID.",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "task_id": {"type": "integer", "description": "ID da tarefa"},
            },
            "required": ["task_id"],
        },
    },
    "add_service_dependency": {
        "description": (
            "Vincula serviço auxiliar à sessão. "
            "service = nome canônico do services-mcp; role classifica o papel (database, cache, auth)."
        ),
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "session_id": {"type": "string", "description": "ID da sessão"},
                "service": {
                    "type": "string",
                    "description": "Nome canônico do serviço no services-mcp",
                },
                "role": {
                    "type": "string",
                    "description": "Papel do serviço na sessão (ex: database, cache, auth)",
                },
                "notes": {
                    "type": "string",
                    "description": "Observações livres sobre o uso do serviço",
                },
            },
            "required": ["session_id", "service"],
        },
    },
    "list_service_dependencies": {
        "description": "Lista os serviços auxiliares vinculados à sessão.",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "session_id": {"type": "string", "description": "ID da sessão"},
            },
            "required": ["session_id"],
        },
    },
    "remove_service_dependency": {
        "description": "Remove o vínculo de um serviço auxiliar com a sessão.",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "session_id": {"type": "string", "description": "ID da sessão"},
                "service": {
                    "type": "string",
                    "description": "Nome canônico do serviço a desvincular",
                },
            },
            "required": ["session_id", "service"],
        },
    },
    "submit_suggestion": {
        "description": (
            "Cross-repo: source_repo propõe melhoria para target_repo. "
            "Entra na fila pending e aparece no resume_session do target_repo."
        ),
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "source_repo": {"type": "string", "description": "Repo que está sugerindo."},
                "target_repo": {
                    "type": "string",
                    "description": "Repo que vai receber/avaliar a sugestão.",
                },
                "title": {"type": "string"},
                "description": {"type": "string"},
                "kind": {"type": "string", "enum": list(SUGGESTION_KINDS)},
                "priority": {"type": "string", "enum": list(SUGGESTION_PRIORITIES)},
                "needs_human_decision": {
                    "type": "boolean",
                    "description": "Default true — sugestões cross-repo passam por decisão humana.",
                    "default": True,
                },
                "source_session_id": {
                    "type": "string",
                    "description": "Sessão originária (opcional, para auditoria).",
                },
            },
            "required": ["source_repo", "target_repo", "title"],
        },
    },
    "list_suggestions": {
        "description": (
            "Lista sugestões cross-repo com filtros. Use target_repo para ver a fila "
            "que cabe ao seu repo trabalhar."
        ),
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "target_repo": {"type": "string"},
                "source_repo": {"type": "string"},
                "status": {"type": "string", "enum": list(SUGGESTION_STATUSES)},
                "limit": {"type": "integer", "default": 50},
            },
            "required": [],
        },
    },
    "get_suggestion": {
        "description": "Retorna o registro completo de uma sugestão pelo ID.",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "suggestion_id": {"type": "integer"},
            },
            "required": ["suggestion_id"],
        },
    },
    "accept_suggestion": {
        "description": (
            "Aceita sugestão e cria task na sessão do target_repo. "
            "Task herda needs_human_decision=true. actor obrigatório."
        ),
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "suggestion_id": {"type": "integer"},
                "session_id": {
                    "type": "string",
                    "description": "Sessão (do target_repo) onde a task será criada.",
                },
                "actor": _ACTOR_SCHEMA,
                "rationale": {
                    "type": "string",
                    "description": "Por que aceitar (opcional mas recomendado).",
                },
                "needs_human_decision": {
                    "type": "boolean",
                    "description": "Sobrescreve o default (true) ao criar a task.",
                },
            },
            "required": ["suggestion_id", "session_id", "actor"],
        },
    },
    "reject_suggestion": {
        "description": "Rejeita uma sugestão pendente com actor + reason obrigatórios.",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "suggestion_id": {"type": "integer"},
                "actor": _ACTOR_SCHEMA,
                "reason": {"type": "string"},
            },
            "required": ["suggestion_id", "actor", "reason"],
        },
    },
    "defer_suggestion": {
        "description": (
            "Difere uma sugestão pendente. actor obrigatório, reason opcional."
        ),
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "suggestion_id": {"type": "integer"},
                "actor": _ACTOR_SCHEMA,
                "reason": {"type": "string"},
            },
            "required": ["suggestion_id", "actor"],
        },
    },
    "supersede_suggestion": {
        "description": (
            "Marca uma sugestão como superseded. actor obrigatório, by_suggestion_id opcional."
        ),
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "suggestion_id": {"type": "integer"},
                "actor": _ACTOR_SCHEMA,
                "by_suggestion_id": {"type": "integer"},
                "reason": {"type": "string"},
            },
            "required": ["suggestion_id", "actor"],
        },
    },
    "list_decisions": {
        "description": (
            "Audit trail: lista decisões registradas com filtros (target, actor, ação, sessão). "
            "Use para governança e revisão de quem decidiu o quê e por quê."
        ),
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "target_type": {
                    "type": "string",
                    "enum": ["task", "suggestion", "session"],
                    "description": "Tipo da entidade alvo.",
                },
                "target_id": {"type": "string", "description": "ID da entidade alvo (string)."},
                "actor_type": {"type": "string", "enum": list(ACTOR_TYPES)},
                "actor_id": {"type": "string"},
                "action": {"type": "string"},
                "session_id": {"type": "string"},
                "limit": {"type": "integer", "default": 100},
            },
            "required": [],
        },
    },
    "get_decision": {
        "description": "Retorna o registro completo de uma decisão pelo ID.",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "decision_id": {"type": "integer"},
            },
            "required": ["decision_id"],
        },
    },
}


# ---------------------------------------------------------------------- #
# HTTP API                                                                #
# ---------------------------------------------------------------------- #
def _build_http_app() -> FastAPI:
    """Build FastAPI app for session-mcp HTTP on port 7100."""
    app = FastAPI(title="session-mcp API", version="0.1.0", docs_url="/docs")
    return app


# ---------------------------------------------------------------------- #
# Server                                                                  #
# ---------------------------------------------------------------------- #
def build_server() -> tuple[Any, SessionSettings, SessionStore, FastAPI]:
    from mcp.server import Server

    settings = get_settings()
    store = SessionStore(settings)
    http_app = _build_http_app()

    server: Server = Server("session-mcp-server")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name=name,
                description=meta["description"],
                inputSchema=meta["schema"],
            )
            for name, meta in _TOOL_SCHEMAS.items()
        ]

    @server.call_tool()
    async def call_tool(
        name: str, arguments: dict[str, Any] | None
    ) -> list[TextContent]:
        args = arguments or {}
        try:
            payload = _dispatch(name, args, store, settings.default_base_branch)
        except KeyError:
            payload = {"error": "unknown_tool", "tool": name}
        except Exception as exc:  # noqa: BLE001
            payload = {"error": "internal_error", "details": str(exc), "tool": name}

        return [TextContent(type="text", text=json.dumps(payload, ensure_ascii=False, indent=2))]

    return server, settings, store, http_app


def _dispatch(
    name: str,
    args: dict[str, Any],
    store: SessionStore,
    default_base_branch: str,
) -> dict:
    if name == "start_session":
        return start_session(
            store,
            default_base_branch,
            title=args.get("title", ""),
            objective=args.get("objective", ""),
            repo=args.get("repo"),
            base_branch=args.get("base_branch"),
        )
    if name == "confirm_branch_created":
        return confirm_branch_created(
            store,
            session_id=args.get("session_id", ""),
            sha=args.get("sha"),
        )
    if name == "save_checkpoint":
        return save_checkpoint(
            store,
            session_id=args.get("session_id", ""),
            summary=args.get("summary", ""),
            context=args.get("context"),
        )
    if name == "update_session":
        return update_session(
            store,
            session_id=args.get("session_id", ""),
            status=args.get("status"),
            progress=args.get("progress"),
        )
    if name == "add_artifact":
        return add_artifact(
            store,
            session_id=args.get("session_id", ""),
            artifact_type=args.get("artifact_type", ""),
            content=args.get("content", ""),
        )
    if name == "list_sessions":
        return list_sessions(
            store,
            status=args.get("status"),
            repo=args.get("repo"),
            limit=args.get("limit", 20),
        )
    if name == "get_session":
        return get_session(store, session_id=args.get("session_id", ""))
    if name == "resume_session":
        return resume_session(store, session_id=args.get("session_id", ""))
    if name == "end_session":
        return end_session(
            store,
            session_id=args.get("session_id", ""),
            actor=args.get("actor"),
            rationale=args.get("rationale", ""),
            final_summary=args.get("final_summary"),
        )
    if name == "add_task":
        return add_task(
            store,
            session_id=args.get("session_id", ""),
            title=args.get("title"),
            description=args.get("description"),
            needs_human_decision=args.get("needs_human_decision", False),
            tasks=args.get("tasks"),
        )
    if name == "approve_task":
        return approve_task(
            store,
            task_id=args.get("task_id", 0),
            decision=args.get("decision", ""),
            actor=args.get("actor"),
            rationale=args.get("rationale"),
            notes=args.get("notes"),
        )
    if name == "start_task":
        return start_task(store, task_id=args.get("task_id", 0))
    if name == "complete_task":
        return complete_task(
            store,
            task_id=args.get("task_id", 0),
            commit_sha=args.get("commit_sha", ""),
            commit_message=args.get("commit_message", ""),
            result=args.get("result"),
        )
    if name == "fail_task":
        return fail_task(
            store,
            task_id=args.get("task_id", 0),
            actor=args.get("actor"),
            reason=args.get("reason", ""),
        )
    if name == "cancel_task":
        return cancel_task(
            store,
            task_id=args.get("task_id", 0),
            actor=args.get("actor"),
            reason=args.get("reason", ""),
        )
    if name == "list_tasks":
        return list_tasks(
            store,
            session_id=args.get("session_id", ""),
            status=args.get("status"),
        )
    if name == "get_task":
        return get_task(store, task_id=args.get("task_id", 0))
    if name == "add_service_dependency":
        return add_service_dependency(
            store,
            session_id=args.get("session_id", ""),
            service=args.get("service", ""),
            role=args.get("role"),
            notes=args.get("notes"),
        )
    if name == "list_service_dependencies":
        return list_service_dependencies(store, session_id=args.get("session_id", ""))
    if name == "remove_service_dependency":
        return remove_service_dependency(
            store,
            session_id=args.get("session_id", ""),
            service=args.get("service", ""),
        )
    if name == "submit_suggestion":
        return submit_suggestion(
            store,
            source_repo=args.get("source_repo", ""),
            target_repo=args.get("target_repo", ""),
            title=args.get("title", ""),
            description=args.get("description"),
            kind=args.get("kind"),
            priority=args.get("priority"),
            needs_human_decision=args.get("needs_human_decision", True),
            source_session_id=args.get("source_session_id"),
        )
    if name == "list_suggestions":
        return list_suggestions_tool(
            store,
            target_repo=args.get("target_repo"),
            source_repo=args.get("source_repo"),
            status=args.get("status"),
            limit=args.get("limit", 50),
        )
    if name == "get_suggestion":
        return get_suggestion_tool(store, suggestion_id=args.get("suggestion_id", 0))
    if name == "accept_suggestion":
        return accept_suggestion(
            store,
            suggestion_id=args.get("suggestion_id", 0),
            session_id=args.get("session_id", ""),
            actor=args.get("actor"),
            rationale=args.get("rationale"),
            needs_human_decision=args.get("needs_human_decision"),
        )
    if name == "reject_suggestion":
        return reject_suggestion(
            store,
            suggestion_id=args.get("suggestion_id", 0),
            actor=args.get("actor"),
            reason=args.get("reason", ""),
        )
    if name == "defer_suggestion":
        return defer_suggestion(
            store,
            suggestion_id=args.get("suggestion_id", 0),
            actor=args.get("actor"),
            reason=args.get("reason"),
        )
    if name == "supersede_suggestion":
        return supersede_suggestion(
            store,
            suggestion_id=args.get("suggestion_id", 0),
            actor=args.get("actor"),
            by_suggestion_id=args.get("by_suggestion_id"),
            reason=args.get("reason"),
        )
    if name == "list_decisions":
        return list_decisions_tool(
            store,
            target_type=args.get("target_type"),
            target_id=args.get("target_id"),
            actor_type=args.get("actor_type"),
            actor_id=args.get("actor_id"),
            action=args.get("action"),
            session_id=args.get("session_id"),
            limit=args.get("limit", 100),
        )
    if name == "get_decision":
        return get_decision_tool(store, decision_id=args.get("decision_id", 0))
    raise KeyError(name)


async def _run() -> None:
    import uvicorn
    from mcp.server.stdio import stdio_server

    server, _settings, _store, http_app = build_server()

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
    asyncio.run(_run())


if __name__ == "__main__":
    main()
