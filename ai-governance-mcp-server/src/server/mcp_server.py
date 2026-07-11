"""Servidor MCP do ai-governance — sidecar kind=mcp_http, GATEWAY-READY (Model C).

Reescrito para o padrão canônico do platform-service-template (v2.0). Implementa o
contrato de integração com o MCP Gateway central (platform-mcp-gateway):
  - docs/standards/STD-MCP-001-mcp-gateway-integration-contract.md  (CI-1..CI-11)
  - docs/standards/STD-SEC-006-token-model-c-inner-token.md          (inner token / audiência)

Pontos gateway-ready:
  1. /mcp/tools/list emite, por tool, inputSchema type=object + capability +
     required_scope + resource_type + data_domain (o gateway NÃO deriva por nome).
  2. /mcp/tools/call re-verifica o **inner Twin Token** (aud=mcp:ai-governance-mcp) via
     JWKS do platform-admin, na PRÓPRIA audiência (defense in depth — CI-4/CI-5). O
     inner token chega em params._meta.twin_token.
  3. tenant_id vem SEMPRE dos claims do token verificado — nunca de argumento do
     cliente (SEC-035 / INV-3).
  4. _EXEMPT_TOOLS (health/status, sem token) e _EXCLUDE_TOOLS (denylist fail-safe).
  5. /docs desabilitado (DOCS_ENABLED=false — HTTP-01).

Transporte: stdio (primário, MCP) + sidecar HTTP (:MCP_PORT, default 7100):
  GET  /v1/health        — liveness (health_path do registro, sem token)
  GET  /mcp/tools/list   — catálogo governado (com metadados de policy)
  POST /mcp/tools/call   — execução (inner token obrigatório, exceto _EXEMPT_TOOLS)

NOTA: ai-governance-mcp é HÍBRIDO. A maioria das tools é compute-only (deriva
diretrizes/políticas/validações da knowledge-base local read-only; não há backend
REST/Trinity), servida pelo ``GovernanceRepository`` singleton compartilhado. Mas os
DOIS stores mutáveis (mural de sugestões + trilha de auditoria) rodam sobre o ORM
canônico, **tenant-scoped e credencial-zero**: são instanciados por-request a partir
de ``for_tenant(tenant_id)`` (tenant dos claims do inner token, ORM-H-12) e o schema é
garantido uma vez por tenant. As tools NÃO conhecem o SDK MCP nem o pool.

Split de dispatch:
  * ``_run_compute`` — tools compute/grafo, síncronas, sobre o ``_get_repo()`` singleton.
  * ``_run_tenant``  — tools de sugestão/auditoria, async, sobre stores tenant-scoped.
stdio serve as compute; as tenant-scoped são gateway-only (recusa fail-closed sem tenant).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

import jwt  # PyJWT — verificação RS256 do inner token via JWKS
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from mcp.server import Server
from mcp.types import TextContent, Tool
from platform_database import close_tenant_pools
from platform_database.orm import configure, for_tenant
from platform_database.orm.dialects import dialect_for_pool
from platform_database.tenant_resolver import get_pool_for_tenant

from ..config.logging import configure_logging
from ..config.settings import NAMESPACE, Settings, get_settings
from ..db.schema import ensure_schema
from ..db.store import AuditStore, SuggestionStore
from ..knowledge.governance_repository import GovernanceRepository
from ..tools import (
    GraphUnavailable,
    SuggestionsUnavailable,
    check_scope,
    create_adr,
    find_consumers_of,
    find_dependencies_of,
    get_agent_guidelines,
    get_audit_log,
    get_contract_change_policy,
    get_fallback_policy,
    get_final_response_template,
    get_forbidden_actions,
    get_layer_policy,
    get_port_map,
    get_pre_execution_checklist,
    get_service_dependencies,
    get_service_metadata,
    get_service_ownership,
    get_suggestion,
    list_suggestions,
    query_ecosystem_graph,
    search_governance_knowledge,
    submit_suggestion,
    update_suggestion_status,
    validate_agent_decision,
    validate_lib_change,
    validate_migration,
)

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------- #
# Enums reutilizados nos schemas de input das tools                      #
# ---------------------------------------------------------------------- #

_LAYER_ENUM = [
    "frontend",
    "backend",
    "database",
    "integrations",
    "infrastructure",
    "security",
    "observability",
    "testing",
]

_CONTRACT_ENUM = ["api", "event", "database", "file", "schema"]

_NODE_KIND_ENUM = ["repository", "service", "library", "contract", "team", "port"]
_RELATION_ENUM = [
    "depends_on",
    "consumes",
    "produces",
    "owns",
    "deprecated_by",
    "replaces",
    "runs_on_port",
    "uses_lib",
    "provides_api",
    "consumes_event",
    "produces_event",
    "based_on",
]

_SUGGESTION_CATEGORY_ENUM = [
    "bug",
    "improvement",
    "refactor",
    "security",
    "performance",
    "docs",
    "test",
    "contract",
    "observability",
]
_SUGGESTION_SEVERITY_ENUM = ["low", "medium", "high", "critical"]
_SUGGESTION_STATUS_ENUM = [
    "pending",
    "acknowledged",
    "accepted",
    "rejected",
    "done",
    "duplicate",
]


# ---------------------------------------------------------------------- #
# Policy metadata por tool (STD-MCP-001 CI-2)                            #
#   capability     — id estável <namespace>.<tool> (computado)           #
#   required_scope — <namespace>:<resource_type>:<verbo> (least-priv)    #
#   resource_type  — tipo de recurso tocado                              #
#   data_domain    — domínio de dado                                     #
# verbo: read = consulta/análise/validação/detecção; write = mutação.    #
# ---------------------------------------------------------------------- #
_POLICY: dict[str, dict[str, str]] = {
    "status": {"resource_type": "status", "verb": "read", "data_domain": "operational"},
    "get_agent_guidelines": {"resource_type": "guideline", "verb": "read", "data_domain": "governance"},
    "get_layer_policy": {"resource_type": "policy", "verb": "read", "data_domain": "governance"},
    "get_forbidden_actions": {"resource_type": "policy", "verb": "read", "data_domain": "governance"},
    "validate_agent_decision": {"resource_type": "decision", "verb": "read", "data_domain": "governance"},
    "get_fallback_policy": {"resource_type": "policy", "verb": "read", "data_domain": "governance"},
    "get_contract_change_policy": {"resource_type": "policy", "verb": "read", "data_domain": "governance"},
    "get_final_response_template": {"resource_type": "template", "verb": "read", "data_domain": "governance"},
    "get_pre_execution_checklist": {
        "resource_type": "checklist",
        "verb": "read",
        "data_domain": "governance",
    },
    "search_governance_knowledge": {
        "resource_type": "knowledge",
        "verb": "read",
        "data_domain": "governance",
    },
    "query_ecosystem_graph": {"resource_type": "graph", "verb": "read", "data_domain": "ecosystem"},
    "find_consumers_of": {"resource_type": "graph", "verb": "read", "data_domain": "ecosystem"},
    "find_dependencies_of": {"resource_type": "graph", "verb": "read", "data_domain": "ecosystem"},
    "get_service_metadata": {"resource_type": "service", "verb": "read", "data_domain": "ecosystem"},
    "submit_suggestion": {"resource_type": "suggestion", "verb": "write", "data_domain": "governance"},
    "list_suggestions": {"resource_type": "suggestion", "verb": "read", "data_domain": "governance"},
    "get_suggestion": {"resource_type": "suggestion", "verb": "read", "data_domain": "governance"},
    "update_suggestion_status": {"resource_type": "suggestion", "verb": "write", "data_domain": "governance"},
    "get_service_ownership": {"resource_type": "service", "verb": "read", "data_domain": "ecosystem"},
    "get_service_dependencies": {"resource_type": "service", "verb": "read", "data_domain": "ecosystem"},
    "get_port_map": {"resource_type": "port", "verb": "read", "data_domain": "operational"},
    "check_scope": {"resource_type": "scope", "verb": "read", "data_domain": "governance"},
    "validate_lib_change": {"resource_type": "lib", "verb": "read", "data_domain": "governance"},
    "validate_migration": {"resource_type": "migration", "verb": "read", "data_domain": "governance"},
    "create_adr": {"resource_type": "adr", "verb": "write", "data_domain": "governance"},
    "get_audit_log": {"resource_type": "audit", "verb": "read", "data_domain": "operational"},
}

_VERB_TO_SCOPE = {"read": "read", "write": "write"}


def _policy_fields(name: str) -> dict[str, str]:
    """Compõe os 4 campos de policy (CI-2) a partir de _POLICY[name]."""
    p = _POLICY[name]
    return {
        "capability": f"{NAMESPACE}.{name}",
        "required_scope": f"{NAMESPACE}:{p['resource_type']}:{_VERB_TO_SCOPE[p['verb']]}",
        "resource_type": p["resource_type"],
        "data_domain": p["data_domain"],
    }


# ---------------------------------------------------------------------- #
# Schemas de input (description + inputSchema) por tool                  #
# inputSchema MUST ser type=object com properties (senão a validação no  #
# front-door é fail-open).                                               #
# ---------------------------------------------------------------------- #
_TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "status": {
        "description": "Retorna o status real do servidor (nome, versão, nº de tools).",
        "schema": {"type": "object", "additionalProperties": False, "properties": {}},
    },
    "get_agent_guidelines": {
        "description": (
            "Retorna diretrizes aplicáveis ao contexto: regras obrigatórias, ações "
            "proibidas e checklist recomendado. Chamar antes de iniciar a tarefa."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "repository_name": {
                    "type": "string",
                    "description": "Nome do repositório alvo (opcional).",
                },
                "task_type": {
                    "type": "string",
                    "description": "feature | bugfix | refactor | migration | infra | docs | test | chore",
                },
                "layer": {"type": "string", "enum": _LAYER_ENUM},
            },
            "additionalProperties": False,
        },
    },
    "get_layer_policy": {
        "description": "Política de uma camada (responsabilidades, can/cannot do, exemplos).",
        "schema": {
            "type": "object",
            "properties": {"layer": {"type": "string", "enum": _LAYER_ENUM}},
            "required": ["layer"],
            "additionalProperties": False,
        },
    },
    "get_forbidden_actions": {
        "description": "Lista canônica de ações proibidas, com motivo e alternativa correta.",
        "schema": {
            "type": "object",
            "properties": {
                "context": {
                    "type": "string",
                    "description": "Filtro opcional: id da regra ou nome de camada.",
                }
            },
            "additionalProperties": False,
        },
    },
    "validate_agent_decision": {
        "description": (
            "Valida uma decisão proposta pelo agente. Bloqueia (approved=false) "
            "decisões com fallback silencioso, hardcoded de credencial, bypass de auth, "
            "mock em prod, remoção de teste, DROP em código de app. Marca como alto "
            "risco contratos sem consumidor declarado, dependências sem justificativa, "
            "alterações fora do escopo."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "repository_name": {"type": "string"},
                "task_description": {"type": "string"},
                "proposed_change": {"type": "string"},
                "affected_files": {"type": "array", "items": {"type": "string"}},
                "affected_layers": {
                    "type": "array",
                    "items": {"type": "string", "enum": _LAYER_ENUM},
                },
                "changes_contracts": {"type": "boolean"},
                "adds_fallback": {"type": "boolean"},
                "adds_dependency": {"type": "boolean"},
                "modifies_security": {"type": "boolean"},
            },
            "required": ["repository_name", "task_description", "proposed_change"],
            "additionalProperties": False,
        },
    },
    "get_fallback_policy": {
        "description": "Política para uso de fallback em um cenário específico.",
        "schema": {
            "type": "object",
            "properties": {
                "scenario": {"type": "string"},
                "service_name": {"type": "string"},
            },
            "required": ["scenario"],
            "additionalProperties": False,
        },
    },
    "get_contract_change_policy": {
        "description": "Regras + checklist + testes obrigatórios para mudança de contrato.",
        "schema": {
            "type": "object",
            "properties": {
                "provider_service": {"type": "string"},
                "consumer_services": {"type": "array", "items": {"type": "string"}},
                "contract_type": {"type": "string", "enum": _CONTRACT_ENUM},
                "proposed_change": {"type": "string"},
            },
            "required": ["provider_service", "contract_type", "proposed_change"],
            "additionalProperties": False,
        },
    },
    "get_final_response_template": {
        "description": "Template obrigatório de resposta final do agente.",
        "schema": {
            "type": "object",
            "properties": {"task_type": {"type": "string"}},
            "additionalProperties": False,
        },
    },
    "get_pre_execution_checklist": {
        "description": "Checklist a executar ANTES de tocar em qualquer arquivo.",
        "schema": {
            "type": "object",
            "properties": {
                "repository_name": {"type": "string"},
                "task_description": {"type": "string"},
                "layer": {"type": "string", "enum": _LAYER_ENUM},
            },
            "required": ["repository_name", "task_description"],
            "additionalProperties": False,
        },
    },
    "search_governance_knowledge": {
        "description": "Busca textual simples na knowledge-base; devolve trechos com fonte.",
        "schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    # ------------------------- ecosystem graph ------------------------- #
    "query_ecosystem_graph": {
        "description": (
            "Consulta o grafo do ecossistema. Sem node_id: lista nós paginados. "
            "Com node_id: vizinhos diretos. query='stats': métricas globais."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "use 'stats' para métricas globais"},
                "kind": {"type": "string", "enum": _NODE_KIND_ENUM},
                "status": {"type": "string", "enum": ["active", "deprecated", "planned"]},
                "node_id": {"type": "string"},
                "relation": {"type": "string", "enum": _RELATION_ENUM},
                "direction": {"type": "string", "enum": ["out", "in", "both"]},
                "filter_text": {"type": "string", "description": "Filtro de texto livre nos nós."},
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "description": "Máximo de resultados. Padrão: 20.",
                },
                "offset": {
                    "type": "integer",
                    "default": 0,
                    "description": "Paginação: pular N resultados.",
                },
            },
            "additionalProperties": False,
        },
    },
    "find_consumers_of": {
        "description": (
            "Lista quem consome o que o nó produz/provê. Resolve via contratos para "
            "serviços (provides_api/produces_event → consumes/consumes_event) e via "
            "uses_lib para libraries."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "node_id": {
                    "type": "string",
                    "description": "id canônico do nó (service/contract/library)",
                },
            },
            "required": ["node_id"],
            "additionalProperties": False,
        },
    },
    "find_dependencies_of": {
        "description": "Lista dependências do nó. Por padrão, apenas diretas (include_transitive=false).",
        "schema": {
            "type": "object",
            "properties": {
                "node_id": {"type": "string"},
                "include_transitive": {
                    "type": "boolean",
                    "default": False,
                    "description": "Se true, inclui dependências transitivas (max_depth até 5).",
                },
                "max_depth": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 5,
                    "default": 1,
                    "description": "Profundidade máxima (só relevante com include_transitive=true).",
                },
            },
            "required": ["node_id"],
            "additionalProperties": False,
        },
    },
    "get_service_metadata": {
        "description": (
            "Devolve atributos completos de um nó + dependências diretas + consumidores "
            "+ canonical_redirect quando o nó está deprecado (aponta para o substituto)."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "node_id": {"type": "string"},
            },
            "required": ["node_id"],
            "additionalProperties": False,
        },
    },
    # ----------------------- cross-repo suggestions ----------------------- #
    "submit_suggestion": {
        "description": (
            "Cria uma sugestão de correção/melhoria para OUTRO serviço/repo. "
            "Use quando, no curso da sua tarefa atual, você notar algo que "
            "melhoraria em outro repositório do ecossistema. target_repo "
            "deve ser o id canônico (ou alias); aliases e nodes deprecados "
            "são automaticamente redirecionados para o canônico."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "source_agent": {
                    "type": "string",
                    "description": "Identificador do agente que abriu (ex.: 'claude-code', 'cursor:caiog').",
                },
                "source_repo": {
                    "type": "string",
                    "description": "Repositório onde o agente estava trabalhando (opcional).",
                },
                "target_repo": {
                    "type": "string",
                    "description": "Repositório destinatário. id canônico do ecosystem.yaml (ou alias).",
                },
                "category": {"type": "string", "enum": _SUGGESTION_CATEGORY_ENUM},
                "severity": {"type": "string", "enum": _SUGGESTION_SEVERITY_ENUM},
                "title": {
                    "type": "string",
                    "maxLength": 200,
                    "description": "Linha curta imperativa. Ex.: 'Adicionar timeout no provider X'.",
                },
                "description": {
                    "type": "string",
                    "maxLength": 8000,
                    "description": "Markdown ok. Inclua contexto, evidência, alternativas avaliadas.",
                },
                "related_files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Caminhos relativos dentro do target_repo.",
                },
                "references": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Links/IDs externos: PR, issue, ADR, commit.",
                },
            },
            "required": [
                "source_agent",
                "target_repo",
                "category",
                "severity",
                "title",
                "description",
            ],
            "additionalProperties": False,
        },
    },
    "list_suggestions": {
        "description": (
            "Lista sugestões com filtros (target_repo, status, category, "
            "severity, source_agent). Default: 20 mais recentes."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "target_repo": {"type": "string"},
                "status": {"type": "string", "enum": _SUGGESTION_STATUS_ENUM},
                "category": {"type": "string", "enum": _SUGGESTION_CATEGORY_ENUM},
                "severity": {"type": "string", "enum": _SUGGESTION_SEVERITY_ENUM},
                "source_agent": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 200},
            },
            "additionalProperties": False,
        },
    },
    "get_suggestion": {
        "description": "Devolve o payload completo de uma sugestão pelo id.",
        "schema": {
            "type": "object",
            "properties": {
                "suggestion_id": {
                    "type": "string",
                    "description": "Formato: YYYYMMDDTHHMMSS-XXXXXXXX",
                },
            },
            "required": ["suggestion_id"],
            "additionalProperties": False,
        },
    },
    "update_suggestion_status": {
        "description": (
            "Muda o status de uma sugestão. Registra histórico (ts, status, "
            "note, by). Use 'acknowledged' quando você viu mas ainda não decidiu, "
            "'accepted' quando vai virar trabalho, 'done' quando implementado."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "suggestion_id": {"type": "string"},
                "new_status": {"type": "string", "enum": _SUGGESTION_STATUS_ENUM},
                "note": {"type": "string"},
                "by": {
                    "type": "string",
                    "description": "Quem fez a mudança (agent id, user, etc.).",
                },
            },
            "required": ["suggestion_id", "new_status"],
            "additionalProperties": False,
        },
    },
    # ----------------------- ownership / scope / libs ----------------------- #
    "get_service_ownership": {
        "description": (
            "O que o serviço possui, o que NÃO deve fazer (explicit_non_responsibilities), "
            "e quem ele chama. Responde 'onde implementar' antes de começar a tarefa. "
            "Dados extraídos do ecosystem.yaml + AGENTS.md §49."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "service_name": {
                    "type": "string",
                    "description": "id canônico ou alias do serviço.",
                },
            },
            "required": ["service_name"],
            "additionalProperties": False,
        },
    },
    "get_service_dependencies": {
        "description": (
            "Upstream (o que o serviço consome) + downstream (quem consome ele). "
            "Use ANTES de validate_agent_decision com changes_contracts=True para "
            "saber quem precisa ser comunicado."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "service_name": {"type": "string"},
            },
            "required": ["service_name"],
            "additionalProperties": False,
        },
    },
    "get_port_map": {
        "description": (
            "Mapeamento canônico porta → serviço (AGENTS.md §47), com próxima porta "
            "livre no range reservado 8022-8029. Útil ao planejar serviço novo."
        ),
        "schema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    "check_scope": {
        "description": (
            "Detecta drift de escopo: volume excessivo, infra central, libs privadas "
            "(HARD STOP §18), múltiplos serviços, arquivos suspeitos para a tarefa "
            "declarada. Retorna risk_level + drift_indicators + required_actions. "
            "Rodar antes de abrir PR."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "task_description": {"type": "string"},
                "changed_files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Lista de paths relativos modificados pela tarefa.",
                },
            },
            "required": ["task_description"],
            "additionalProperties": False,
        },
    },
    "validate_lib_change": {
        "description": (
            "HARD STOP §18 AGENTS.md: bloqueia mudanças em libs privadas (platform-*-lib, "
            "platform-db-vector). Retorna template de LIB CHANGE REQUEST pré-preenchido "
            "com consumidores identificados automaticamente no grafo, e os next steps "
            "para aprovação por @caiog."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "lib_name": {"type": "string"},
                "proposed_change": {
                    "type": "string",
                    "description": "Descrição da mudança que se quer fazer na lib.",
                },
            },
            "required": ["lib_name", "proposed_change"],
            "additionalProperties": False,
        },
    },
    # ----------------------- migration validation ----------------------- #
    "validate_migration": {
        "description": (
            "Valida conteúdo de arquivo de migration Alembic contra AGENTS.md §29: "
            "sem ORM (op.execute(sa.text(...))), idempotência (IF NOT EXISTS), sem "
            "DROP destrutivo na upgrade(), downgrade obrigatório. O caller PASSA o "
            "conteúdo como string — a tool não toca em filesystem."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "Conteúdo completo do arquivo de migration.",
                },
            },
            "required": ["content"],
            "additionalProperties": False,
        },
    },
    # ----------------------- ADR creation ----------------------- #
    "create_adr": {
        "description": (
            "Cria docs/decisions/adr-NNNN.md no repositório alvo. Numeração automática "
            "(próximo número livre). Use quando uma decisão arquitetural justifica "
            "ADR (substituir biblioteca, mudar padrão de cache, novo protocolo)."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Título curto da decisão."},
                "context": {"type": "string", "description": "Cenário, forças, restrições."},
                "decision": {
                    "type": "string",
                    "description": "Decisão em voz ativa: 'Vamos usar X para Y porque Z.'",
                },
                "consequences": {
                    "type": "string",
                    "description": "Positivas, negativas, neutras.",
                },
                "repo_path": {
                    "type": "string",
                    "description": "Caminho absoluto do repo alvo. Default: pai da knowledge-base.",
                },
            },
            "required": ["title", "context", "decision", "consequences"],
            "additionalProperties": False,
        },
    },
    # ----------------------- audit log ----------------------- #
    "get_audit_log": {
        "description": (
            "Consulta a trilha de auditoria de validate_agent_decision. "
            "query='stats' devolve métricas agregadas (total, bloqueados, "
            "by_risk_level, top_repos, top_violations). Sem query: lista "
            "registros em ordem cronológica reversa, com filtros opcionais."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "'stats' para métricas agregadas; omitir para listar.",
                },
                "filter_repo": {
                    "type": "string",
                    "description": "Filtro por repositório (substring, case-insensitive).",
                },
                "risk_level": {
                    "type": "string",
                    "enum": ["low", "medium", "high", "critical"],
                    "description": "Filtro exato por nível de risco.",
                },
                "approved": {
                    "type": "boolean",
                    "description": "true=só aprovados; false=só bloqueados.",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 500,
                    "description": "Máximo de registros (default 50).",
                },
                "offset": {
                    "type": "integer",
                    "minimum": 0,
                    "description": "Pular os primeiros N resultados (paginação).",
                },
            },
            "additionalProperties": False,
        },
    },
}

# Health/status são encaminhadas SEM inner token (CI-7 exempt_tools — só tokenless).
_EXEMPT_TOOLS: frozenset[str] = frozenset({"status"})
# Denylist fail-safe: tools que retornam segredos NUNCA saem pelo gateway (CI-7).
_EXCLUDE_TOOLS: frozenset[str] = frozenset()

# Campos de policy repassados no /mcp/tools/list (o gateway lê estes campos).
_POLICY_FIELDS = ("capability", "required_scope", "resource_type", "data_domain")

# Garante que _POLICY cobre exatamente todas as tools declaradas (least-privilege
# completo — falha no import se alguma tool ficar sem policy). Não usa assert p/
# não ser removível com `python -O`.
if set(_POLICY.keys()) != set(_TOOL_SCHEMAS.keys()):  # pragma: no cover - guarda de integridade
    raise RuntimeError("_POLICY não cobre exatamente as tools de _TOOL_SCHEMAS")


# ---------------------------------------------------------------------- #
# Repositório da KB — singleton lazy (compute-only, read-only)           #
# A mural de sugestões e a trilha de auditoria NÃO são singletons: são    #
# stores ORM tenant-scoped, criados por-request a partir da TenantSession.#
# ---------------------------------------------------------------------- #
_repo: GovernanceRepository | None = None


def _get_repo() -> GovernanceRepository:
    global _repo
    if _repo is None:
        _repo = GovernanceRepository(kb_path=get_settings().kb_path)
    return _repo


def _status() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": NAMESPACE,
        "version": "0.1.0",
        "tools": len(_TOOL_SCHEMAS),
    }


# ── Verificação do inner Twin Token (STD-SEC-006 / CI-4/CI-5) ─────────────────


def _verify_inner_token(twin_token: str, settings: Settings) -> dict[str, Any]:
    """Re-verifica o inner Twin Token na PRÓPRIA audiência (mcp:ai-governance-mcp).

    O gateway já verificou o front token; o backend é 'one more verified client'
    (defense in depth). RS256 via JWKS do platform-admin; audiência exata; jti
    obrigatório. Levanta em qualquer falha (fail-closed).
    """
    if not settings.mcp_twin_audience or not settings.url_admin_twin_jwks:
        raise PermissionError(
            "integração com o gateway não configurada: defina MCP_TWIN_AUDIENCE "
            "(mcp:ai-governance-mcp) e URL_ADMIN_TWIN_JWKS (ver STD-SEC-006 / IT-006)."
        )
    signing_key = jwt.PyJWKClient(settings.url_admin_twin_jwks).get_signing_key_from_jwt(twin_token)
    return jwt.decode(
        twin_token,
        signing_key.key,
        algorithms=["RS256"],  # RS256 exclusivo (STD-SEC-001)
        audience=settings.mcp_twin_audience,  # a falha de integração nº 1
        options={"require": ["exp", "aud", "jti"]},  # sem jti → rejeita (JTI_REQUIRED)
    )


# ── Roteamento p/ as funções puras ───────────────────────────────────────────
# As tools de sugestão/auditoria são tenant-scoped (tocam o DB do tenant); as demais
# são compute puras sobre a KB read-only. O tenant vem SEMPRE dos claims do inner
# token (SEC-035 / INV-3), nunca de argumento do cliente.
_TENANT_SCOPED_TOOLS: frozenset[str] = frozenset(
    {
        "submit_suggestion",
        "list_suggestions",
        "get_suggestion",
        "update_suggestion_status",
        "validate_agent_decision",
        "get_audit_log",
    }
)

# Guarda de integridade: toda tool tenant-scoped precisa existir no catálogo.
if not _TENANT_SCOPED_TOOLS <= set(_TOOL_SCHEMAS):  # pragma: no cover - guarda de import
    raise RuntimeError("_TENANT_SCOPED_TOOLS referencia tool ausente em _TOOL_SCHEMAS")


def _arg(args: dict[str, Any], key: str, default: Any = None) -> Any:
    """Acessa um argumento da tool call como ``Any``.

    ``dict.get`` sob ``dict[str, Any]`` devolve ``Any | None``, o que faz o mypy
    reclamar ao repassar para parâmetros ``str`` obrigatórios. As funções puras já
    validam a presença/tipo (levantando ``ValueError`` → payload de erro), então o
    comportamento em runtime é idêntico ao de ``args.get`` — só o tipo estático muda.
    """
    return args.get(key, default)


def _route_compute(
    name: str,
    args: dict[str, Any],
    repo: GovernanceRepository,
) -> dict[str, Any]:
    """Roteia tools COMPUTE (síncronas, sobre a KB read-only). KeyError se desconhecida."""
    if name == "get_agent_guidelines":
        return get_agent_guidelines(
            repo,
            repository_name=_arg(args, "repository_name"),
            task_type=_arg(args, "task_type"),
            layer=_arg(args, "layer"),
        )
    if name == "get_layer_policy":
        return get_layer_policy(repo, layer=_arg(args, "layer"))
    if name == "get_forbidden_actions":
        return get_forbidden_actions(repo, context=_arg(args, "context"))
    if name == "get_fallback_policy":
        return get_fallback_policy(
            repo,
            scenario=_arg(args, "scenario"),
            service_name=_arg(args, "service_name"),
        )
    if name == "get_contract_change_policy":
        return get_contract_change_policy(
            repo,
            provider_service=_arg(args, "provider_service"),
            consumer_services=_arg(args, "consumer_services"),
            contract_type=_arg(args, "contract_type"),
            proposed_change=_arg(args, "proposed_change"),
        )
    if name == "get_final_response_template":
        return get_final_response_template(repo, task_type=_arg(args, "task_type"))
    if name == "get_pre_execution_checklist":
        return get_pre_execution_checklist(
            repo,
            repository_name=_arg(args, "repository_name"),
            task_description=_arg(args, "task_description"),
            layer=_arg(args, "layer"),
        )
    if name == "search_governance_knowledge":
        return search_governance_knowledge(
            repo,
            query=_arg(args, "query"),
            limit=_arg(args, "limit"),
        )
    if name == "query_ecosystem_graph":
        return query_ecosystem_graph(
            repo,
            query=_arg(args, "query"),
            kind=_arg(args, "kind"),
            status=_arg(args, "status"),
            relation=_arg(args, "relation"),
            direction=_arg(args, "direction"),
            node_id=_arg(args, "node_id"),
            filter_text=_arg(args, "filter_text"),
            limit=_arg(args, "limit", 20),
            offset=_arg(args, "offset", 0),
        )
    if name == "find_consumers_of":
        return find_consumers_of(repo, node_id=_arg(args, "node_id"))
    if name == "find_dependencies_of":
        return find_dependencies_of(
            repo,
            node_id=_arg(args, "node_id"),
            include_transitive=_arg(args, "include_transitive", False),
            max_depth=_arg(args, "max_depth", 1),
        )
    if name == "get_service_metadata":
        return get_service_metadata(repo, node_id=_arg(args, "node_id"))
    if name == "get_service_ownership":
        return get_service_ownership(repo, service_name=_arg(args, "service_name"))
    if name == "get_service_dependencies":
        return get_service_dependencies(repo, service_name=_arg(args, "service_name"))
    if name == "get_port_map":
        return get_port_map(repo)
    if name == "check_scope":
        return check_scope(
            repo,
            task_description=_arg(args, "task_description"),
            changed_files=_arg(args, "changed_files"),
        )
    if name == "validate_lib_change":
        return validate_lib_change(
            repo,
            lib_name=_arg(args, "lib_name"),
            proposed_change=_arg(args, "proposed_change"),
        )
    if name == "validate_migration":
        return validate_migration(repo, content=_arg(args, "content"))
    if name == "create_adr":
        return create_adr(
            repo,
            title=_arg(args, "title"),
            context=_arg(args, "context"),
            decision=_arg(args, "decision"),
            consequences=_arg(args, "consequences"),
            repo_path=_arg(args, "repo_path"),
        )
    raise KeyError(name)


async def _route_tenant(
    name: str,
    args: dict[str, Any],
    repo: GovernanceRepository,
    suggestions: SuggestionStore,
    audit: AuditStore,
) -> dict[str, Any]:
    """Roteia tools TENANT-SCOPED (async, sobre os stores do tenant). KeyError se desconhecida."""
    if name == "submit_suggestion":
        return await submit_suggestion(
            repo,
            suggestions,
            source_agent=_arg(args, "source_agent"),
            source_repo=_arg(args, "source_repo"),
            target_repo=_arg(args, "target_repo"),
            category=_arg(args, "category"),
            severity=_arg(args, "severity"),
            title=_arg(args, "title"),
            description=_arg(args, "description"),
            related_files=_arg(args, "related_files"),
            references=_arg(args, "references"),
        )
    if name == "list_suggestions":
        return await list_suggestions(
            repo,
            suggestions,
            target_repo=_arg(args, "target_repo"),
            status=_arg(args, "status"),
            category=_arg(args, "category"),
            severity=_arg(args, "severity"),
            source_agent=_arg(args, "source_agent"),
            limit=_arg(args, "limit"),
        )
    if name == "get_suggestion":
        return await get_suggestion(suggestions, suggestion_id=_arg(args, "suggestion_id"))
    if name == "update_suggestion_status":
        return await update_suggestion_status(
            suggestions,
            suggestion_id=_arg(args, "suggestion_id"),
            new_status=_arg(args, "new_status"),
            note=_arg(args, "note"),
            by=_arg(args, "by"),
        )
    if name == "validate_agent_decision":
        result = validate_agent_decision(
            repo,
            repository_name=_arg(args, "repository_name"),
            task_description=_arg(args, "task_description"),
            proposed_change=_arg(args, "proposed_change"),
            affected_files=_arg(args, "affected_files"),
            affected_layers=_arg(args, "affected_layers"),
            changes_contracts=_arg(args, "changes_contracts", False),
            adds_fallback=_arg(args, "adds_fallback", False),
            adds_dependency=_arg(args, "adds_dependency", False),
            modifies_security=_arg(args, "modifies_security", False),
        )
        # Persiste na trilha de auditoria do tenant; falha NÃO silenciosa — loga o erro.
        try:
            await audit.record(result, result.get("input_summary"))
        except Exception:  # noqa: BLE001
            _log.warning("audit_write_failed", extra={"extras": {"tool": name}})
        return result
    if name == "get_audit_log":
        return await get_audit_log(
            audit,
            query=_arg(args, "query"),
            filter_repo=_arg(args, "filter_repo"),
            risk_level=_arg(args, "risk_level"),
            approved=_arg(args, "approved"),
            limit=_arg(args, "limit", 50),
            offset=_arg(args, "offset", 0),
        )
    raise KeyError(name)


def _graph_unavailable_payload(name: str) -> dict[str, Any]:
    _log.warning("graph_unavailable", extra={"extras": {"tool": name}})
    return {
        "error": "ecosystem_graph_unavailable",
        "details": (
            "ecosystem.yaml ausente ou inválido. Crie/corrija o arquivo na "
            "knowledge-base e reinicie o servidor."
        ),
        "tool": name,
    }


def _validation_error_payload(name: str, exc: ValueError) -> dict[str, Any]:
    _log.warning("tool_validation_error", extra={"extras": {"tool": name, "error": str(exc)}})
    return {"error": "validation_error", "details": str(exc), "tool": name}


def _run_compute(name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Executa uma tool compute (síncrona). status é repo-free; as demais usam a KB.

    Erros de domínio viram payload de erro claro; tool desconhecida propaga KeyError.
    """
    if name == "status":
        return _status()
    repo = _get_repo()
    try:
        return _route_compute(name, args, repo)
    except GraphUnavailable:
        return _graph_unavailable_payload(name)
    except ValueError as exc:
        return _validation_error_payload(name, exc)


# ── Tenant plumbing (credencial-zero) ─────────────────────────────────────────
# Bootstrap de schema roda UMA vez por tenant/processo (idempotente de qualquer forma).
_SCHEMA_READY: set[str] = set()
_SCHEMA_LOCK = asyncio.Lock()


async def _ensure_tenant_schema(settings: Settings, tenant_id: str) -> None:
    """Garante as tabelas no banco do tenant (uma vez por processo). O engine é o do
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


async def _run_tenant(name: str, args: dict[str, Any], settings: Settings, tenant_id: str) -> dict[str, Any]:
    """Abre a sessão tenant-scoped (credencial-zero), garante o schema e despacha.

    Os stores (sugestões + auditoria) são criados a partir da sessão do tenant; a KB
    read-only continua vindo do singleton compartilhado (compute)."""
    await _ensure_tenant_schema(settings, tenant_id)
    repo = _get_repo()
    async with for_tenant(tenant_id) as session:
        suggestions = SuggestionStore(session)
        audit = AuditStore(session)
        try:
            return await _route_tenant(name, args, repo, suggestions, audit)
        except GraphUnavailable:
            return _graph_unavailable_payload(name)
        except SuggestionsUnavailable:
            _log.warning("suggestions_unavailable", extra={"extras": {"tool": name}})
            return {
                "error": "suggestions_store_unavailable",
                "details": "Store de sugestões indisponível para este tenant.",
                "tool": name,
            }
        except ValueError as exc:
            return _validation_error_payload(name, exc)


# ── HTTP Sidecar ──────────────────────────────────────────────────────────────


def _build_http_app(settings: Settings) -> FastAPI:
    """Cria o sidecar HTTP (health + bridge governado /mcp/tools/*).

    Stateless quanto a store: as tools tenant-scoped abrem uma sessão por-request
    (credencial-zero) a partir do tenant nos claims do inner token; as compute usam a
    KB read-only compartilhada."""
    app = FastAPI(
        title="ai-governance-mcp API",
        version="0.1.0",
        docs_url="/docs" if settings.docs_enabled else None,  # false em todo ambiente
        redoc_url=None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
    )

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
            entry.update(_policy_fields(name))
            tools.append(entry)
        return {"result": {"tools": tools}}

    @app.post("/mcp/tools/call")
    async def http_call_tool(body: dict) -> Any:
        params = body.get("params", body)
        name = params.get("name", "")
        arguments = dict(params.get("arguments", {}) or {})

        if name in _EXCLUDE_TOOLS:
            return JSONResponse(status_code=403, content={"error": "tool_excluded", "tool": name})

        # Execução (não-exempt) exige inner token válido; tenant vem dos claims.
        tenant_id: str | None = None
        if name not in _EXEMPT_TOOLS:
            twin_token = (params.get("_meta") or {}).get("twin_token")
            if not twin_token:
                return JSONResponse(status_code=401, content={"error": "missing_twin_token"})
            try:
                claims = _verify_inner_token(twin_token, settings)
            except Exception as exc:  # noqa: BLE001 — fail-closed em qualquer falha de verificação
                _log.warning("inner_token_rejected", extra={"extras": {"tool": name, "detail": str(exc)}})
                return JSONResponse(status_code=401, content={"error": "invalid_twin_token"})
            claim_tenant = claims.get("tenant_id")
            if not claim_tenant:
                return JSONResponse(status_code=401, content={"error": "missing_tenant_scope"})
            tenant_id = str(claim_tenant)

        if name not in _TOOL_SCHEMAS:
            return JSONResponse(status_code=404, content={"error": "unknown_tool", "tool": name})

        try:
            if name in _TENANT_SCOPED_TOOLS:
                if tenant_id is None:  # tools tenant-scoped nunca são exempt (defense-in-depth)
                    return JSONResponse(status_code=401, content={"error": "missing_tenant_scope"})
                # SEC-035 / INV-3: tenant SEMPRE dos claims, nunca de argumento do cliente.
                payload = await _run_tenant(name, arguments, settings, tenant_id)
            else:
                payload = _run_compute(name, arguments)
        except Exception as exc:  # noqa: BLE001 — a resposta carrega o erro
            _log.exception("tool_internal_error", extra={"extras": {"tool": name}})
            payload = {"error": "internal_error", "detail": str(exc), "tool": name}
        content = [TextContent(type="text", text=json.dumps(payload, ensure_ascii=False, indent=2))]
        return {"result": {"content": [c.model_dump(exclude_none=True) for c in content]}}

    @app.on_event("shutdown")
    async def _close_pools() -> None:
        # Fecha os pools por-tenant no shutdown (registry compartilhado da lib).
        await close_tenant_pools()

    return app


# ── Server (stdio + sidecar) ──────────────────────────────────────────────────


def build_server() -> tuple[Any, Settings, FastAPI]:
    """Inicializa o MCP Server (stdio), settings e o sidecar HTTP.

    ``orm.configure(settings)`` registra a fonte admin (ADMIN_DB_*) usada para resolver
    o tenant → credencial do seu banco via PLATFORMS (credencial-zero, ORM-H-12)."""
    settings = get_settings()
    settings.enforce_security_invariants()  # fail-fast no boot (STD-SEC-001/004/006)
    configure_logging(settings)  # logging estruturado JSON (STD-OBS-001)
    configure(settings)  # bootstrap credencial-zero: admin source p/ for_tenant
    http_app = _build_http_app(settings)
    _log.info(
        "ai_governance_mcp_ready",
        extra={"extras": {"tools": len(_TOOL_SCHEMAS), "engine": settings.DB_ENGINE}},
    )

    server: Server = Server("ai-governance-mcp-server")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(name=name, description=meta["description"], inputSchema=meta["schema"])
            for name, meta in _TOOL_SCHEMAS.items()
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any] | None) -> list[TextContent]:
        # O transporte stdio não carrega o inner token (logo, sem tenant). As tools
        # tenant-scoped (sugestão/auditoria) são gateway-only: recusadas fail-closed
        # aqui; o tenant vem dos claims verificados no sidecar HTTP. As compute (KB
        # read-only) rodam normalmente no stdio.
        args = arguments or {}
        _log.info("tool_called", extra={"extras": {"tool": name, "args_keys": sorted(args.keys())}})
        if name not in _TOOL_SCHEMAS:
            payload: dict[str, Any] = {"error": "unknown_tool", "tool": name}
            _log.error("unknown_tool", extra={"extras": {"tool": name}})
        elif name in _TENANT_SCOPED_TOOLS:
            payload = {
                "error": "tenant_context_required",
                "tool": name,
                "detail": (
                    "tool tenant-scoped e gateway-only; chame via o sidecar HTTP "
                    "(/mcp/tools/call) com o inner Twin Token — o tenant vem dos claims."
                ),
            }
        else:
            try:
                payload = _run_compute(name, args)
            except Exception as exc:  # noqa: BLE001
                payload = {"error": "internal_error", "detail": str(exc), "tool": name}
                _log.exception("tool_internal_error", extra={"extras": {"tool": name}})
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
