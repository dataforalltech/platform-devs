"""Servidor MCP do session — sidecar kind=mcp_http, GATEWAY-READY (Model C).

Reescrito para o padrão canônico do platform-service-template (v2.0). Implementa o
contrato de integração com o MCP Gateway central (platform-mcp-gateway):
  - docs/standards/STD-MCP-001-mcp-gateway-integration-contract.md  (CI-1..CI-11)
  - docs/standards/STD-SEC-006-token-model-c-inner-token.md          (inner token / audiência)

Pontos gateway-ready:
  1. /mcp/tools/list emite, por tool, inputSchema type=object + capability +
     required_scope + resource_type + data_domain (o gateway NÃO deriva por nome).
  2. /mcp/tools/call re-verifica o **inner Twin Token** (aud=mcp:session-mcp) via
     JWKS do platform-admin, na PRÓPRIA audiência (defense in depth — CI-4/CI-5). O
     inner token chega em params._meta.twin_token.
  3. tenant_id vem SEMPRE dos claims do token verificado — nunca de argumento do
     cliente (SEC-035 / INV-3). As tools de sessão não o consomem (é só p/
     governança), então o dispatcher o remove antes de chamar a função.
  4. _EXEMPT_TOOLS (tokenless) e _EXCLUDE_TOOLS (denylist fail-safe).
  5. /docs desabilitado (DOCS_ENABLED=false — HTTP-01).

Transporte: stdio (primário, MCP) + sidecar HTTP (:MCP_PORT, default 7100):
  GET  /v1/health        — liveness (health_path do registro, sem token)
  GET  /mcp/tools/list   — catálogo governado (com metadados de policy)
  POST /mcp/tools/call   — execução (inner token obrigatório, exceto _EXEMPT_TOOLS)

NOTA: session-mcp persiste em ``SessionStore`` (SQLite embarcado, hermético), então
o dispatcher recebe (store, settings) e injeta ambos nas tools — preservando a
lógica original de src/tools/.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import jwt  # PyJWT — verificação RS256 do inner token via JWKS
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from mcp.server import Server
from mcp.types import TextContent, Tool

from ..config.settings import NAMESPACE, SessionSettings, get_settings
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

_log = logging.getLogger(__name__)


class _JSONEncoder(json.JSONEncoder):
    """Serializa tipos extras: datetime, date, Decimal."""

    def default(self, o: Any) -> Any:
        if isinstance(o, (datetime, date)):
            return o.isoformat()
        if isinstance(o, Decimal):
            return float(o)
        return super().default(o)


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

# ── Tool Schemas + Policy metadata (STD-MCP-001 CI-2) ─────────────────────────
# Cada tool declara, além de description/schema, os 4 campos de política:
#   capability     — id estável <namespace>.<tool> (não derivar por nome no gateway)
#   required_scope — escopo de execução no formato dominio:tipo:acao (least-privilege)
#   resource_type  — tipo de recurso tocado
#   data_domain    — domínio de dado (governa HITL floor / classificação LGPD)
# inputSchema MUST ser type=object com properties (senão a validação no front-door
# é fail-open). Mutação → verbo :write; consulta → :read.
#
# Para manter o dicionário de schemas legível, a policy é declarada de forma compacta
# em _POLICY_SPEC = (resource_type, ação) e expandida (capability + required_scope +
# data_domain) em _tool_policy(). data_domain é 'governance' para o audit trail de
# decisões e 'session' para o restante.
# ─────────────────────────────────────────────────────────────────────────────
_POLICY_SPEC: dict[str, tuple[str, str]] = {
    # ── Sessões ──
    "start_session": ("session", "write"),
    "confirm_branch_created": ("session", "write"),
    "save_checkpoint": ("session", "write"),
    "update_session": ("session", "write"),
    "add_artifact": ("session", "write"),
    "list_sessions": ("session", "read"),
    "get_session": ("session", "read"),
    "resume_session": ("session", "write"),  # reativa sessão pausada → mutação
    "end_session": ("session", "write"),
    # ── Tasks ──
    "add_task": ("task", "write"),
    "approve_task": ("task", "write"),
    "start_task": ("task", "write"),
    "complete_task": ("task", "write"),
    "fail_task": ("task", "write"),
    "cancel_task": ("task", "write"),
    "list_tasks": ("task", "read"),
    "get_task": ("task", "read"),
    # ── Service dependencies ──
    "add_service_dependency": ("service", "write"),
    "list_service_dependencies": ("service", "read"),
    "remove_service_dependency": ("service", "write"),
    # ── Cross-repo suggestions ──
    "submit_suggestion": ("suggestion", "write"),
    "list_suggestions": ("suggestion", "read"),
    "get_suggestion": ("suggestion", "read"),
    "accept_suggestion": ("suggestion", "write"),
    "reject_suggestion": ("suggestion", "write"),
    "defer_suggestion": ("suggestion", "write"),
    "supersede_suggestion": ("suggestion", "write"),
    # ── Decisions (audit trail) ──
    "list_decisions": ("decision", "read"),
    "get_decision": ("decision", "read"),
}

# resource_type → data_domain (o audit de decisões é governança).
_DATA_DOMAIN: dict[str, str] = {"decision": "governance"}


def _tool_policy(name: str) -> dict[str, str]:
    """Expande a policy compacta nos 4 campos que o gateway lê (CI-2)."""
    resource_type, action = _POLICY_SPEC[name]
    return {
        "capability": f"{NAMESPACE}.{name}",
        "required_scope": f"{NAMESPACE}:{resource_type}:{action}",
        "resource_type": resource_type,
        "data_domain": _DATA_DOMAIN.get(resource_type, "session"),
    }


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
                    "description": "Branch base (default: develop) — usada como from_ref ao criar a branch da sessão.",  # noqa: E501
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
                    "description": "Contexto estruturado opcional (arquivos pendentes, decisões, próximos passos)",  # noqa: E501
                },
            },
            "required": ["session_id", "summary"],
        },
    },
    "update_session": {
        "description": (
            "Atualiza o status e/ou progresso de uma sessão. Status: active | paused | completed."
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
            "Retorna dados completos de uma sessão: " "metadados, último checkpoint e contagem de artefatos."
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
            "Cancela uma tarefa (de 'pending' ou 'in_progress'). " "actor + reason obrigatórios (governança)."
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
        "description": "Difere uma sugestão pendente. actor obrigatório, reason opcional.",
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
        "description": ("Marca uma sugestão como superseded. actor obrigatório, by_suggestion_id opcional."),
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

# Todo schema DEVE ter policy declarada (fail-safe: descobre drift na importação).
assert set(_POLICY_SPEC) == set(_TOOL_SCHEMAS), "policy/schemas mismatch"  # noqa: S101

# Tools encaminhadas SEM inner token (CI-7 exempt_tools — só tokenless). session-mcp
# não expõe tool pública/tokenless: TODA execução exige inner token válido.
_EXEMPT_TOOLS: frozenset[str] = frozenset()
# Denylist fail-safe: tools que NUNCA saem pelo gateway (CI-7).
_EXCLUDE_TOOLS: frozenset[str] = frozenset()

# Campos de policy repassados no /mcp/tools/list (o gateway lê estes campos).
_POLICY_FIELDS = ("capability", "required_scope", "resource_type", "data_domain")


# ── Verificação do inner Twin Token (STD-SEC-006 / CI-4/CI-5) ─────────────────


def _verify_inner_token(twin_token: str, settings: SessionSettings) -> dict[str, Any]:
    """Re-verifica o inner Twin Token na PRÓPRIA audiência (mcp:session-mcp).

    O gateway já verificou o front token; o backend é 'one more verified client'
    (defense in depth). RS256 via JWKS do platform-admin; audiência exata; jti
    obrigatório. Levanta em qualquer falha (fail-closed).
    """
    if not settings.mcp_twin_audience or not settings.url_admin_twin_jwks:
        raise PermissionError(
            "integração com o gateway não configurada: defina MCP_TWIN_AUDIENCE "
            "(mcp:session-mcp) e URL_ADMIN_TWIN_JWKS (ver STD-SEC-006 / IT-006)."
        )
    signing_key = jwt.PyJWKClient(settings.url_admin_twin_jwks).get_signing_key_from_jwt(twin_token)
    return jwt.decode(
        twin_token,
        signing_key.key,
        algorithms=["RS256"],  # RS256 exclusivo (STD-SEC-001)
        audience=settings.mcp_twin_audience,  # a falha de integração nº 1
        options={"require": ["exp", "aud", "jti"]},  # sem jti → rejeita (JTI_REQUIRED)
    )


# ── Dispatcher (backend-backed: store + settings injetados nas tools) ─────────


def _dispatch(
    name: str, args: dict[str, Any], store: SessionStore, settings: SessionSettings
) -> dict[str, Any]:
    """Despacha a chamada para a função de tool, preservando a lógica original.

    ``tenant_id`` é injetado pelo PEP nos args (INV-3) apenas para governança; as
    tools de sessão não o consomem, então é removido antes da chamada.
    """
    a = {k: v for k, v in args.items() if k != "tenant_id"}
    base = settings.default_base_branch

    if name == "start_session":
        return start_session(
            store,
            base,
            title=a.get("title", ""),
            objective=a.get("objective", ""),
            repo=a.get("repo", ""),
            base_branch=a.get("base_branch"),
        )
    if name == "confirm_branch_created":
        return confirm_branch_created(store, session_id=a.get("session_id", ""), sha=a.get("sha"))
    if name == "save_checkpoint":
        return save_checkpoint(
            store,
            session_id=a.get("session_id", ""),
            summary=a.get("summary", ""),
            context=a.get("context"),
        )
    if name == "update_session":
        return update_session(
            store,
            session_id=a.get("session_id", ""),
            status=a.get("status"),
            progress=a.get("progress"),
        )
    if name == "add_artifact":
        return add_artifact(
            store,
            session_id=a.get("session_id", ""),
            artifact_type=a.get("artifact_type", ""),
            content=a.get("content", ""),
        )
    if name == "list_sessions":
        return list_sessions(
            store,
            status=a.get("status"),
            repo=a.get("repo"),
            limit=a.get("limit", 20),
        )
    if name == "get_session":
        return get_session(store, session_id=a.get("session_id", ""))
    if name == "resume_session":
        return resume_session(store, session_id=a.get("session_id", ""))
    if name == "end_session":
        return end_session(
            store,
            session_id=a.get("session_id", ""),
            actor=a.get("actor"),
            rationale=a.get("rationale", ""),
            final_summary=a.get("final_summary"),
        )
    if name == "add_task":
        return add_task(
            store,
            session_id=a.get("session_id", ""),
            title=a.get("title"),
            description=a.get("description"),
            needs_human_decision=a.get("needs_human_decision", False),
            tasks=a.get("tasks"),
        )
    if name == "approve_task":
        return approve_task(
            store,
            task_id=a.get("task_id", 0),
            decision=a.get("decision", ""),
            actor=a.get("actor"),
            rationale=a.get("rationale"),
            notes=a.get("notes"),
        )
    if name == "start_task":
        return start_task(store, task_id=a.get("task_id", 0))
    if name == "complete_task":
        return complete_task(
            store,
            task_id=a.get("task_id", 0),
            commit_sha=a.get("commit_sha", ""),
            commit_message=a.get("commit_message", ""),
            result=a.get("result"),
        )
    if name == "fail_task":
        return fail_task(
            store,
            task_id=a.get("task_id", 0),
            actor=a.get("actor"),
            reason=a.get("reason", ""),
        )
    if name == "cancel_task":
        return cancel_task(
            store,
            task_id=a.get("task_id", 0),
            actor=a.get("actor"),
            reason=a.get("reason", ""),
        )
    if name == "list_tasks":
        return list_tasks(store, session_id=a.get("session_id", ""), status=a.get("status"))
    if name == "get_task":
        return get_task(store, task_id=a.get("task_id", 0))
    if name == "add_service_dependency":
        return add_service_dependency(
            store,
            session_id=a.get("session_id", ""),
            service=a.get("service", ""),
            role=a.get("role"),
            notes=a.get("notes"),
        )
    if name == "list_service_dependencies":
        return list_service_dependencies(store, session_id=a.get("session_id", ""))
    if name == "remove_service_dependency":
        return remove_service_dependency(
            store,
            session_id=a.get("session_id", ""),
            service=a.get("service", ""),
        )
    if name == "submit_suggestion":
        return submit_suggestion(
            store,
            source_repo=a.get("source_repo", ""),
            target_repo=a.get("target_repo", ""),
            title=a.get("title", ""),
            description=a.get("description"),
            kind=a.get("kind"),
            priority=a.get("priority"),
            needs_human_decision=a.get("needs_human_decision", True),
            source_session_id=a.get("source_session_id"),
        )
    if name == "list_suggestions":
        return list_suggestions_tool(
            store,
            target_repo=a.get("target_repo"),
            source_repo=a.get("source_repo"),
            status=a.get("status"),
            limit=a.get("limit", 50),
        )
    if name == "get_suggestion":
        return get_suggestion_tool(store, suggestion_id=a.get("suggestion_id", 0))
    if name == "accept_suggestion":
        return accept_suggestion(
            store,
            suggestion_id=a.get("suggestion_id", 0),
            session_id=a.get("session_id", ""),
            actor=a.get("actor"),
            rationale=a.get("rationale"),
            needs_human_decision=a.get("needs_human_decision"),
        )
    if name == "reject_suggestion":
        return reject_suggestion(
            store,
            suggestion_id=a.get("suggestion_id", 0),
            actor=a.get("actor"),
            reason=a.get("reason", ""),
        )
    if name == "defer_suggestion":
        return defer_suggestion(
            store,
            suggestion_id=a.get("suggestion_id", 0),
            actor=a.get("actor"),
            reason=a.get("reason"),
        )
    if name == "supersede_suggestion":
        return supersede_suggestion(
            store,
            suggestion_id=a.get("suggestion_id", 0),
            actor=a.get("actor"),
            by_suggestion_id=a.get("by_suggestion_id"),
            reason=a.get("reason"),
        )
    if name == "list_decisions":
        return list_decisions_tool(
            store,
            target_type=a.get("target_type"),
            target_id=a.get("target_id"),
            actor_type=a.get("actor_type"),
            actor_id=a.get("actor_id"),
            action=a.get("action"),
            session_id=a.get("session_id"),
            limit=a.get("limit", 100),
        )
    if name == "get_decision":
        return get_decision_tool(store, decision_id=a.get("decision_id", 0))
    raise KeyError(name)


# ── HTTP Sidecar ──────────────────────────────────────────────────────────────


def _build_http_app(settings: SessionSettings, store: SessionStore) -> FastAPI:
    """Cria o sidecar HTTP (health + bridge governado /mcp/tools/*)."""
    app = FastAPI(
        title="session-mcp API",
        version="0.1.0",
        docs_url="/docs" if settings.docs_enabled else None,  # false em todo ambiente
        redoc_url=None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
    )

    @app.get("/v1/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "service": "session-mcp", "tools": len(_TOOL_SCHEMAS)}

    @app.get("/mcp/tools/list")
    def http_list_tools() -> dict:
        tools = []
        for name, meta in _TOOL_SCHEMAS.items():
            entry: dict[str, Any] = {
                "name": name,
                "description": meta["description"],
                "inputSchema": meta["schema"],
            }
            entry.update(_tool_policy(name))
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
            payload = _dispatch(name, arguments, store, settings)
        except KeyError:
            return JSONResponse(status_code=404, content={"error": "unknown_tool", "tool": name})
        except Exception as exc:  # noqa: BLE001 — a resposta carrega o erro
            _log.exception("tool_internal_error: %s", name)
            payload = {"error": "internal_error", "detail": str(exc), "tool": name}
        text = json.dumps(payload, ensure_ascii=False, indent=2, cls=_JSONEncoder)
        return {"result": {"content": [{"type": "text", "text": text}]}}

    return app


# ── Server (stdio + sidecar) ──────────────────────────────────────────────────


def build_server() -> tuple[Any, SessionSettings, SessionStore, FastAPI]:
    """Inicializa o MCP Server (stdio), settings, o store e o sidecar HTTP."""
    settings = get_settings()
    logging.basicConfig(level=settings.log_level, format="%(levelname)s %(name)s %(message)s")
    store = SessionStore(settings)
    http_app = _build_http_app(settings, store)
    _log.info("session_mcp_ready tools=%d", len(_TOOL_SCHEMAS))

    server: Server = Server("session-mcp-server")

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
            payload = _dispatch(name, args, store, settings)
        except KeyError:
            payload = {"error": "unknown_tool", "tool": name}
        except Exception as exc:  # noqa: BLE001
            payload = {"error": "internal_error", "detail": str(exc), "tool": name}
            _log.exception("tool_internal_error: %s", name)
        return [
            TextContent(
                type="text",
                text=json.dumps(payload, ensure_ascii=False, indent=2, cls=_JSONEncoder),
            )
        ]

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
