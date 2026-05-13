"""Servidor MCP — registra as tools e expõe via stdio.

Esta é a única camada que conhece o SDK MCP. As tools são funções puras
em `src/tools/` que recebem o `GovernanceRepository` e devolvem dicts.
Aqui apenas:

  1. Carregamos a knowledge-base e instanciamos o repositório uma única vez.
  2. Declaramos o schema JSON de cada tool (input).
  3. Roteamos as chamadas do MCP para a função correspondente.
  4. Tratamos erros de validação devolvendo um payload `{"error": ...}` claro.

Para rodar: `python -m src.server.mcp_server` ou `ai-governance-mcp-server`
(ver pyproject.toml).
"""

from __future__ import annotations

import os

import asyncio
import json
from typing import Any

from fastapi import FastAPI
from mcp.server import Server
from mcp.types import TextContent, Tool

from ..config.settings import get_settings
from ..knowledge.audit_store import AuditStore
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
from ..utils.logger import get_logger, setup_logging

_log = get_logger(__name__)

# ---------------------------------------------------------------------- #
# Schemas de input das tools                                             #
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

_TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "get_agent_guidelines": {
        "description": (
            "Retorna diretrizes aplicáveis ao contexto: regras obrigatórias, ações "
            "proibidas e checklist recomendado. Chamar antes de iniciar a tarefa."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "repository_name": {"type": "string", "description": "Nome do repositório alvo (opcional)."},
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
                "limit": {"type": "integer", "default": 20, "description": "Máximo de resultados. Padrão: 20."},
                "offset": {"type": "integer", "default": 0, "description": "Paginação: pular N resultados."},
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
                "node_id": {"type": "string", "description": "id canônico do nó (service/contract/library)"},
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


# ---------------------------------------------------------------------- #
# Construção do servidor                                                  #
# ---------------------------------------------------------------------- #


def _build_http_app() -> FastAPI:
    app = FastAPI(title="Ai Governance API", version="0.1.0", docs_url="/docs")

    @app.get("/v1/health")
    def health() -> dict:
        return {"status": "ok", "service": "ai-governance-mcp"}

    return app


def build_server() -> tuple[Any, ...]:
    """Cria o servidor MCP, registra tools e devolve junto o repositório.

    Separado de `main()` para permitir testes que carregam o servidor sem
    abrir conexão stdio.
    """
    settings = get_settings()
    http_app = _build_http_app()
    setup_logging(level=settings.log_level, fmt=settings.log_format)

    repo = GovernanceRepository(
        kb_path=settings.kb_path,
        suggestions_path=settings.effective_suggestions_path,
    )
    audit = AuditStore(path=settings.effective_audit_path)

    server: Server = Server("ai-governance-mcp-server")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(name=name, description=meta["description"], inputSchema=meta["schema"])
            for name, meta in _TOOL_SCHEMAS.items()
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any] | None) -> list[TextContent]:
        args = arguments or {}
        _log.info(
            "tool_called",
            extra={"extras": {"tool": name, "args_keys": sorted(args.keys())}},
        )
        try:
            payload = _dispatch(name, args, repo, audit)
        except GraphUnavailable:
            payload = {
                "error": "ecosystem_graph_unavailable",
                "details": (
                    "ecosystem.yaml ausente ou inválido. Crie/corrija o arquivo na "
                    "knowledge-base e reinicie o servidor."
                ),
                "tool": name,
            }
            _log.warning("graph_unavailable", extra={"extras": {"tool": name}})
        except SuggestionsUnavailable:
            payload = {
                "error": "suggestions_store_unavailable",
                "details": (
                    "Store de sugestões indisponível (filesystem inacessível). "
                    "Verifique GOVERNANCE_SUGGESTIONS_PATH e permissões."
                ),
                "tool": name,
            }
            _log.warning("suggestions_unavailable", extra={"extras": {"tool": name}})
        except ValueError as e:
            payload = {"error": "validation_error", "details": str(e), "tool": name}
            _log.warning(
                "tool_validation_error",
                extra={"extras": {"tool": name, "error": str(e)}},
            )
        except KeyError:
            payload = {"error": "unknown_tool", "tool": name}
            _log.error("unknown_tool", extra={"extras": {"tool": name}})
        except Exception as e:  # noqa: BLE001 — único ponto onde é aceitável
            payload = {"error": "internal_error", "details": str(e), "tool": name}
            _log.exception("tool_internal_error", extra={"extras": {"tool": name}})

        return [TextContent(type="text", text=json.dumps(payload, ensure_ascii=False, indent=2))]

    @http_app.get("/mcp/tools/list")
    async def http_list_tools() -> dict:
        tools = await list_tools()
        return {"result": {"tools": [t.model_dump(exclude_none=True) for t in tools]}}

    @http_app.post("/mcp/tools/call")
    async def http_call_tool(body: dict) -> dict:
        params = body.get("params", body)
        result = await call_tool(params.get("name", ""), params.get("arguments", {}))
        return {"result": {"content": [r.model_dump(exclude_none=True) for r in result]}}

    return server, repo, http_app

def _dispatch(name: str, args: dict[str, Any], repo: GovernanceRepository, audit: AuditStore) -> dict:
    """Roteia a chamada para a função pura correspondente."""
    if name == "get_agent_guidelines":
        return get_agent_guidelines(
            repo,
            repository_name=args.get("repository_name"),
            task_type=args.get("task_type"),
            layer=args.get("layer"),
        )
    if name == "get_layer_policy":
        return get_layer_policy(repo, layer=args.get("layer"))
    if name == "get_forbidden_actions":
        return get_forbidden_actions(repo, context=args.get("context"))
    if name == "validate_agent_decision":
        result = validate_agent_decision(
            repo,
            repository_name=args.get("repository_name"),
            task_description=args.get("task_description"),
            proposed_change=args.get("proposed_change"),
            affected_files=args.get("affected_files"),
            affected_layers=args.get("affected_layers"),
            changes_contracts=args.get("changes_contracts", False),
            adds_fallback=args.get("adds_fallback", False),
            adds_dependency=args.get("adds_dependency", False),
            modifies_security=args.get("modifies_security", False),
        )
        # Persiste na trilha de auditoria; falha silenciosa para não bloquear resposta.
        try:
            audit.record(result, result.get("input_summary"))
        except Exception:  # noqa: BLE001
            _log.warning("audit_write_failed", extra={"extras": {"tool": name}})
        return result
    if name == "get_fallback_policy":
        return get_fallback_policy(
            repo,
            scenario=args.get("scenario"),
            service_name=args.get("service_name"),
        )
    if name == "get_contract_change_policy":
        return get_contract_change_policy(
            repo,
            provider_service=args.get("provider_service"),
            consumer_services=args.get("consumer_services"),
            contract_type=args.get("contract_type"),
            proposed_change=args.get("proposed_change"),
        )
    if name == "get_final_response_template":
        return get_final_response_template(repo, task_type=args.get("task_type"))
    if name == "get_pre_execution_checklist":
        return get_pre_execution_checklist(
            repo,
            repository_name=args.get("repository_name"),
            task_description=args.get("task_description"),
            layer=args.get("layer"),
        )
    if name == "search_governance_knowledge":
        return search_governance_knowledge(
            repo,
            query=args.get("query"),
            limit=args.get("limit"),
        )
    if name == "query_ecosystem_graph":
        return query_ecosystem_graph(
            repo,
            query=args.get("query"),
            kind=args.get("kind"),
            status=args.get("status"),
            relation=args.get("relation"),
            direction=args.get("direction"),
            node_id=args.get("node_id"),
            filter_text=args.get("filter_text"),
            limit=args.get("limit", 20),
            offset=args.get("offset", 0),
        )
    if name == "find_consumers_of":
        return find_consumers_of(repo, node_id=args.get("node_id"))
    if name == "find_dependencies_of":
        return find_dependencies_of(
            repo,
            node_id=args.get("node_id"),
            include_transitive=args.get("include_transitive", False),
            max_depth=args.get("max_depth", 1),
        )
    if name == "get_service_metadata":
        return get_service_metadata(repo, node_id=args.get("node_id"))
    if name == "submit_suggestion":
        return submit_suggestion(
            repo,
            source_agent=args.get("source_agent"),
            source_repo=args.get("source_repo"),
            target_repo=args.get("target_repo"),
            category=args.get("category"),
            severity=args.get("severity"),
            title=args.get("title"),
            description=args.get("description"),
            related_files=args.get("related_files"),
            references=args.get("references"),
        )
    if name == "list_suggestions":
        return list_suggestions(
            repo,
            target_repo=args.get("target_repo"),
            status=args.get("status"),
            category=args.get("category"),
            severity=args.get("severity"),
            source_agent=args.get("source_agent"),
            limit=args.get("limit"),
        )
    if name == "get_suggestion":
        return get_suggestion(repo, suggestion_id=args.get("suggestion_id"))
    if name == "update_suggestion_status":
        return update_suggestion_status(
            repo,
            suggestion_id=args.get("suggestion_id"),
            new_status=args.get("new_status"),
            note=args.get("note"),
            by=args.get("by"),
        )
    if name == "get_service_ownership":
        return get_service_ownership(repo, service_name=args.get("service_name"))
    if name == "get_service_dependencies":
        return get_service_dependencies(repo, service_name=args.get("service_name"))
    if name == "get_port_map":
        return get_port_map(repo)
    if name == "check_scope":
        return check_scope(
            repo,
            task_description=args.get("task_description"),
            changed_files=args.get("changed_files"),
        )
    if name == "validate_lib_change":
        return validate_lib_change(
            repo,
            lib_name=args.get("lib_name"),
            proposed_change=args.get("proposed_change"),
        )
    if name == "validate_migration":
        return validate_migration(repo, content=args.get("content"))
    if name == "create_adr":
        return create_adr(
            repo,
            title=args.get("title"),
            context=args.get("context"),
            decision=args.get("decision"),
            consequences=args.get("consequences"),
            repo_path=args.get("repo_path"),
        )
    if name == "get_audit_log":
        return get_audit_log(
            repo,
            audit,
            query=args.get("query"),
            filter_repo=args.get("filter_repo"),
            risk_level=args.get("risk_level"),
            approved=args.get("approved"),
            limit=args.get("limit", 50),
            offset=args.get("offset", 0),
        )
    raise KeyError(name)


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
    """Entry point para `ai-governance-mcp-server` no PATH."""
    asyncio.run(_run())


if __name__ == "__main__":
    main()
