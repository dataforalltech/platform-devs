"""Catálogo de tools + dispatcher do domínio *pipeline* (consolidado no devteam-mcp).

Fatia "de negócio" do antigo `pipeline-mcp-server/src/server/mcp_server.py`: mantém
intactos o ``_TOOL_SCHEMAS`` (schemas + os metadados de policy por tool) e o ``_dispatch``
(roteamento op → handler). O que ficou de FORA é o boot/serve/segurança (FastAPI, PEP
inner-token, stdio, tenant plumbing) — responsabilidade do AGREGADOR
(`src/server/mcp_server.py`), compartilhada por todos os domínios.

Diferenças vs. o server-fonte (strangler — fiel, sem inventar comportamento):
  * ``capability`` passa a ``devteam-mcp.pipeline_<op>`` (namespace do server consolidado +
    nome de tool já prefixado pelo domínio — o gateway não deriva por nome).
  * ``required_scope`` passa a ``pipeline:<recurso>:<ação>`` — PRESERVA o least-privilege
    por-tool, só troca o antigo prefixo de namespace ``pipeline-mcp`` pelo domínio
    ``pipeline`` (``resource_type``/``data_domain`` ficam com os valores ORIGINAIS do fonte).
    Ambos são reescritos por um loop de injeção logo após ``_TOOL_SCHEMAS`` (o dict em si
    fica byte-a-byte com o fonte).
  * As CHAVES de ``_TOOL_SCHEMAS`` continuam os nomes de op SEM prefixo (``register_pipeline``);
    o ``plugin.register()`` prefixa (``pipeline_register_pipeline``) e o ``plugin.dispatch``
    retira o prefixo antes de chamar ``dispatch`` daqui — a lógica de roteamento fica
    byte-a-byte com o fonte.
  * O ``_run_tool`` do fonte (schema-ensure + ``for_tenant`` + ``PipelineStore(session)``)
    some: o agregador já garante o schema e abre a sessão tenant-scoped, e o ``plugin``
    constrói a ``PipelineStore``. A ``dispatch`` daqui recebe a ``PipelineStore`` e constrói
    o ``PipelineSettings`` (dep de RUNTIME: PAT do GitHub via env) para delegar ao
    ``_dispatch`` do fonte (byte-a-byte).
"""

from __future__ import annotations

from typing import Any

from .config.settings import PipelineSettings, get_settings
from .db.store import PipelineStore
from .tools import (
    add_gate_result,
    approve_promotion,
    block_service,
    clear_gates,
    get_gate_status,
    get_pipeline,
    get_pipeline_overview,
    get_promotion_history,
    list_pipeline,
    promote_service,
    register_pipeline,
    rollback,
    set_pipeline_config,
    watch_prs,
)

# Domínio canônico deste plugin — usado no capability/required_scope e como prefixo de
# tool (o agregador descobre o domínio por ``<domain>_<op>``).
DOMAIN = "pipeline"

# ── Tool Schemas + Policy metadata (STD-MCP-001 CI-2) ─────────────────────────
# Cada tool declara, além de description/schema, os 4 campos de política:
#   capability     — id estável <namespace>.<tool> (não derivar por nome no gateway)
#   required_scope — escopo de execução no formato dominio:tipo:acao (least-privilege)
#   resource_type  — tipo de recurso tocado
#   data_domain    — domínio de dado (governa HITL floor / classificação LGPD)
# inputSchema MUST ser type=object com properties (senão a validação no front-door
# é fail-open). Consultas usam verbo :read; mutações/trigger usam :write.
# ─────────────────────────────────────────────────────────────────────────────
_TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    # ── Pipeline ──────────────────────────────────────────────────────────── #
    "register_pipeline": {
        "description": (
            "Registra um serviço no pipeline. "
            "Se o serviço já existir, atualiza repo e base_branch. "
            "Retorna action=created ou action=updated."
        ),
        "capability": "pipeline-mcp.register_pipeline",
        "required_scope": "pipeline-mcp:pipeline:write",
        "resource_type": "pipeline",
        "data_domain": "pipeline",
        "schema": {
            "type": "object",
            "properties": {
                "service": {"type": "string", "description": "Nome único do serviço."},
                "repo": {
                    "type": "string",
                    "description": "Nome do repositório (ex: org/repo-name).",
                },
                "base_branch": {
                    "type": "string",
                    "description": "Branch base de desenvolvimento. Default: develop.",
                    "default": "develop",
                },
            },
            "required": ["service", "repo"],
            "additionalProperties": False,
        },
    },
    "get_pipeline": {
        "description": (
            "Retorna o status atual do pipeline de um serviço, "
            "incluindo ambiente atual, status de bloqueio e últimas 10 promoções."
        ),
        "capability": "pipeline-mcp.get_pipeline",
        "required_scope": "pipeline-mcp:pipeline:read",
        "resource_type": "pipeline",
        "data_domain": "pipeline",
        "schema": {
            "type": "object",
            "properties": {
                "service": {"type": "string", "description": "Nome do serviço."},
            },
            "required": ["service"],
            "additionalProperties": False,
        },
    },
    "list_pipeline": {
        "description": (
            "Lista serviços registrados no pipeline. "
            "Suporta filtros por env (dev/homol/prod/blocked/rollback) e status (active/blocked)."
        ),
        "capability": "pipeline-mcp.list_pipeline",
        "required_scope": "pipeline-mcp:pipeline:read",
        "resource_type": "pipeline",
        "data_domain": "pipeline",
        "schema": {
            "type": "object",
            "properties": {
                "env": {
                    "type": "string",
                    "enum": ["dev", "homol", "prod", "blocked", "rollback"],
                    "description": "Filtrar por ambiente atual do serviço.",
                },
                "status": {
                    "type": "string",
                    "enum": ["active", "blocked"],
                    "description": "Filtrar por status de bloqueio.",
                },
            },
            "additionalProperties": False,
        },
    },
    "promote_service": {
        "description": (
            "Promove um serviço entre ambientes (dev→homol ou homol→prod). "
            "Verifica todos os gates obrigatórios antes de promover. "
            "DEV→HML e HML→PROD: cria PR via GitHub e aguarda aprovação humana (status=waiting_approval). "
            "Após aprovação humana, chame approve_promotion(promotion_id). "
            "Retorna can_promote=false com lista de gates pendentes se houver falhas."
        ),
        "capability": "pipeline-mcp.promote_service",
        "required_scope": "pipeline-mcp:promotion:write",
        "resource_type": "promotion",
        "data_domain": "pipeline",
        "schema": {
            "type": "object",
            "properties": {
                "service": {"type": "string", "description": "Nome do serviço."},
                "from_env": {
                    "type": "string",
                    "enum": ["dev", "homol"],
                    "description": "Ambiente de origem.",
                },
                "to_env": {
                    "type": "string",
                    "enum": ["homol", "prod"],
                    "description": "Ambiente de destino.",
                },
                "promoted_by": {
                    "type": "string",
                    "description": "Identificador de quem solicitou a promoção (usuário ou agente).",
                },
                "reason": {
                    "type": "string",
                    "description": "Motivo da promoção (opcional).",
                },
            },
            "required": ["service", "from_env", "to_env", "promoted_by"],
            "additionalProperties": False,
        },
    },
    "approve_promotion": {
        "description": (
            "Registra aprovação humana de uma promoção HML ou PROD e executa o merge da PR. "
            "Deve ser chamado após o humano aprovar a PR no GitHub. "
            "Atualiza o ambiente do serviço para to_env após merge bem-sucedido."
        ),
        "capability": "pipeline-mcp.approve_promotion",
        "required_scope": "pipeline-mcp:promotion:write",
        "resource_type": "promotion",
        "data_domain": "pipeline",
        "schema": {
            "type": "object",
            "properties": {
                "promotion_id": {
                    "type": "integer",
                    "description": "ID da promoção retornado por promote_service.",
                },
                "approved_by": {
                    "type": "string",
                    "description": "Identificador de quem aprovou (usuário GitHub ou nome).",
                },
            },
            "required": ["promotion_id", "approved_by"],
            "additionalProperties": False,
        },
    },
    "watch_prs": {
        "description": (
            "Escaneia PRs abertas nos repos registrados no pipeline. "
            "PRs targeting 'develop': auto-aprova e mergia se gates passam (DEV — autonomia total). "
            "PRs targeting 'homol' ou 'main': lista para aprovação humana sem tocar. "
            "Configure PIPELINE_GITHUB_TOKEN e PIPELINE_GITHUB_ORG para usar."
        ),
        "capability": "pipeline-mcp.watch_prs",
        "required_scope": "pipeline-mcp:pipeline:write",
        "resource_type": "pipeline",
        "data_domain": "pipeline",
        "schema": {
            "type": "object",
            "properties": {
                "repos": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Repos específicos a verificar. Default: todos os registrados.",
                },
            },
            "additionalProperties": False,
        },
    },
    "block_service": {
        "description": (
            "Bloqueia a promoção de um serviço no pipeline. "
            "Um serviço bloqueado não pode ser promovido até ser desbloqueado manualmente."
        ),
        "capability": "pipeline-mcp.block_service",
        "required_scope": "pipeline-mcp:pipeline:write",
        "resource_type": "pipeline",
        "data_domain": "pipeline",
        "schema": {
            "type": "object",
            "properties": {
                "service": {"type": "string", "description": "Nome do serviço."},
                "reason": {"type": "string", "description": "Motivo do bloqueio."},
                "blocked_by": {
                    "type": "string",
                    "description": "Identificador de quem bloqueou.",
                },
            },
            "required": ["service", "reason", "blocked_by"],
            "additionalProperties": False,
        },
    },
    "rollback": {
        "description": (
            "Registra um rollback de versão para um serviço em um ambiente. "
            "Atualiza o status do serviço para 'rollback' e registra no histórico."
        ),
        "capability": "pipeline-mcp.rollback",
        "required_scope": "pipeline-mcp:promotion:write",
        "resource_type": "promotion",
        "data_domain": "pipeline",
        "schema": {
            "type": "object",
            "properties": {
                "service": {"type": "string", "description": "Nome do serviço."},
                "env": {
                    "type": "string",
                    "enum": ["dev", "homol", "prod"],
                    "description": "Ambiente onde o rollback será realizado.",
                },
                "to_version": {
                    "type": "string",
                    "description": "Versão/SHA/tag para onde reverter.",
                },
                "rolled_back_by": {
                    "type": "string",
                    "description": "Identificador de quem executou o rollback.",
                },
                "reason": {
                    "type": "string",
                    "description": "Motivo do rollback (opcional).",
                },
            },
            "required": ["service", "env", "to_version", "rolled_back_by"],
            "additionalProperties": False,
        },
    },
    # ── Gates ─────────────────────────────────────────────────────────────── #
    "add_gate_result": {
        "description": (
            "Registra o resultado de um gate de qualidade para um serviço/ambiente. "
            "Types válidos: qa_tests, security_scan, pr_approved, health_check, "
            "manual_approval, audit_compliance. "
            "Se o gate já existir, atualiza o resultado."
        ),
        "capability": "pipeline-mcp.add_gate_result",
        "required_scope": "pipeline-mcp:gate:write",
        "resource_type": "gate",
        "data_domain": "pipeline",
        "schema": {
            "type": "object",
            "properties": {
                "service": {"type": "string", "description": "Nome do serviço."},
                "env": {
                    "type": "string",
                    "enum": ["dev", "homol", "prod"],
                    "description": "Ambiente ao qual o gate se refere.",
                },
                "gate_type": {
                    "type": "string",
                    "enum": [
                        "qa_tests",
                        "security_scan",
                        "pr_approved",
                        "health_check",
                        "manual_approval",
                        "audit_compliance",
                    ],
                    "description": "Tipo do gate.",
                },
                "passed": {
                    "type": "boolean",
                    "description": "True se o gate passou, False se falhou.",
                },
                "details": {
                    "type": "string",
                    "description": "Detalhes adicionais (URL do relatório, mensagem de erro, etc.).",
                },
                "evaluated_by": {
                    "type": "string",
                    "description": "Identificador de quem/o que avaliou o gate.",
                },
            },
            "required": ["service", "env", "gate_type", "passed"],
            "additionalProperties": False,
        },
    },
    "get_gate_status": {
        "description": (
            "Retorna o status de todos os gates para um serviço/ambiente. "
            "Indica quais gates são obrigatórios, quais passaram, falharam ou estão ausentes. "
            "Inclui campo can_promote: true/false."
        ),
        "capability": "pipeline-mcp.get_gate_status",
        "required_scope": "pipeline-mcp:gate:read",
        "resource_type": "gate",
        "data_domain": "pipeline",
        "schema": {
            "type": "object",
            "properties": {
                "service": {"type": "string", "description": "Nome do serviço."},
                "env": {
                    "type": "string",
                    "enum": ["dev", "homol", "prod"],
                    "description": "Ambiente a consultar.",
                },
            },
            "required": ["service", "env"],
            "additionalProperties": False,
        },
    },
    "clear_gates": {
        "description": (
            "Limpa todos os resultados de gates de um serviço/ambiente. "
            "Útil para forçar re-avaliação completa antes de uma nova promoção."
        ),
        "capability": "pipeline-mcp.clear_gates",
        "required_scope": "pipeline-mcp:gate:write",
        "resource_type": "gate",
        "data_domain": "pipeline",
        "schema": {
            "type": "object",
            "properties": {
                "service": {"type": "string", "description": "Nome do serviço."},
                "env": {
                    "type": "string",
                    "enum": ["dev", "homol", "prod"],
                    "description": "Ambiente cujos gates serão limpos.",
                },
            },
            "required": ["service", "env"],
            "additionalProperties": False,
        },
    },
    # ── History ───────────────────────────────────────────────────────────── #
    "get_promotion_history": {
        "description": (
            "Retorna o histórico de promoções. "
            "Se service for fornecido, filtra pelo serviço. "
            "Retorna até limit registros ordenados por data decrescente."
        ),
        "capability": "pipeline-mcp.get_promotion_history",
        "required_scope": "pipeline-mcp:promotion:read",
        "resource_type": "promotion",
        "data_domain": "pipeline",
        "schema": {
            "type": "object",
            "properties": {
                "service": {
                    "type": "string",
                    "description": "Nome do serviço (opcional, para filtrar).",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 200,
                    "default": 20,
                    "description": "Número máximo de registros. Default: 20.",
                },
            },
            "additionalProperties": False,
        },
    },
    "get_pipeline_overview": {
        "description": (
            "Retorna visão geral do pipeline: total de serviços por ambiente, "
            "contagem de bloqueados/ativos, e serviços com gates com falha."
        ),
        "capability": "pipeline-mcp.get_pipeline_overview",
        "required_scope": "pipeline-mcp:pipeline:read",
        "resource_type": "pipeline",
        "data_domain": "pipeline",
        "schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    "set_pipeline_config": {
        "description": (
            "Configura quais gates são obrigatórios por ambiente para um serviço. "
            "Substitui a configuração padrão (homol: [qa_tests, pr_approved]; "
            "prod: [qa_tests, security_scan, pr_approved, health_check])."
        ),
        "capability": "pipeline-mcp.set_pipeline_config",
        "required_scope": "pipeline-mcp:pipeline:write",
        "resource_type": "pipeline",
        "data_domain": "pipeline",
        "schema": {
            "type": "object",
            "properties": {
                "service": {"type": "string", "description": "Nome do serviço."},
                "gates_required": {
                    "type": "object",
                    "description": (
                        "Mapa de ambiente → lista de gates obrigatórios. "
                        'Ex: {"homol": ["qa_tests"], "prod": ["qa_tests", "pr_approved"]}'
                    ),
                    "additionalProperties": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
            },
            "required": ["service", "gates_required"],
            "additionalProperties": False,
        },
    },
}


# Reescreve APENAS capability e required_scope para o namespace/domínio consolidado
# (o dict acima fica byte-a-byte com o fonte; resource_type/data_domain intactos):
#   capability     = devteam-mcp.<domínio>_<op>            (id estável; gateway não deriva)
#   required_scope = <domínio>:<recurso>:<ação>            (least-privilege por-tool intacto;
#                    só troca o antigo namespace ``pipeline-mcp`` pelo domínio ``pipeline``)
for _name, _meta in _TOOL_SCHEMAS.items():
    _meta["capability"] = f"devteam-mcp.{DOMAIN}_{_name}"
    # required_scope do fonte = ``pipeline-mcp:<recurso>:<ação>`` → dropa o 1º segmento
    # (namespace antigo) e reprefixa com o domínio canônico.
    _scope = _meta["required_scope"].split(":", 1)[1]
    _meta["required_scope"] = f"{DOMAIN}:{_scope}"


# ── Dispatcher (stateful: recebe store; tenant_id só p/ governança) ───────────


async def _dispatch(
    name: str,
    args: dict[str, Any],
    settings: PipelineSettings,
    store: PipelineStore,
) -> dict[str, Any]:
    """Despacha a chamada para a tool (async). O tenant NÃO viaja nos args (INV-3):
    o ``store`` já está ligado ao pool do tenant (resolvido dos claims do inner token)."""
    # ── Pipeline ──────────────────────────────────────────────────────────── #
    if name == "register_pipeline":
        return await register_pipeline(
            store,
            service=args["service"],
            repo=args["repo"],
            base_branch=args.get("base_branch", "develop"),
        )
    if name == "get_pipeline":
        return await get_pipeline(store, service=args["service"])
    if name == "list_pipeline":
        return await list_pipeline(store, env=args.get("env"), status=args.get("status"))
    if name == "promote_service":
        return await promote_service(
            store,
            service=args["service"],
            from_env=args["from_env"],
            to_env=args["to_env"],
            promoted_by=args["promoted_by"],
            reason=args.get("reason"),
            github_token=settings.github_token,
            github_org=settings.github_org,
        )
    if name == "approve_promotion":
        return await approve_promotion(
            store,
            promotion_id=args["promotion_id"],
            approved_by=args["approved_by"],
            github_token=settings.github_token,
            github_org=settings.github_org,
        )
    if name == "watch_prs":
        return await watch_prs(
            store,
            github_token=settings.github_token,
            github_org=settings.github_org,
            repos=args.get("repos"),
        )
    if name == "block_service":
        return await block_service(
            store,
            service=args["service"],
            reason=args["reason"],
            blocked_by=args["blocked_by"],
        )
    if name == "rollback":
        return await rollback(
            store,
            service=args["service"],
            env=args["env"],
            to_version=args["to_version"],
            rolled_back_by=args["rolled_back_by"],
            reason=args.get("reason"),
        )
    # ── Gates ─────────────────────────────────────────────────────────────── #
    if name == "add_gate_result":
        return await add_gate_result(
            store,
            service=args["service"],
            env=args["env"],
            gate_type=args["gate_type"],
            passed=args["passed"],
            details=args.get("details"),
            evaluated_by=args.get("evaluated_by"),
        )
    if name == "get_gate_status":
        return await get_gate_status(store, service=args["service"], env=args["env"])
    if name == "clear_gates":
        return await clear_gates(store, service=args["service"], env=args["env"])
    # ── History ───────────────────────────────────────────────────────────── #
    if name == "get_promotion_history":
        return await get_promotion_history(store, service=args.get("service"), limit=args.get("limit", 20))
    if name == "get_pipeline_overview":
        return await get_pipeline_overview(store)
    if name == "set_pipeline_config":
        return await set_pipeline_config(
            store, service=args["service"], gates_required=args["gates_required"]
        )
    raise KeyError(name)


# ── Dispatcher público (recebe a Store do domínio ligada ao tenant) ────────────


async def dispatch(name: str, args: dict[str, Any], store: PipelineStore) -> dict[str, Any]:
    """Despacha a chamada (async). ``name`` é o nome de op SEM prefixo de domínio (o
    ``plugin.dispatch`` já o retirou) e ``store`` já está ligado ao pool do tenant.

    Constrói o ``PipelineSettings`` (dep de RUNTIME: PAT/org do GitHub via env, resolvido
    fora do import/smoke) e delega ao ``_dispatch`` do server-fonte (byte-a-byte). O
    ``_run_tool`` do fonte (schema-ensure + ``for_tenant`` + ``PipelineStore(session)``)
    fica no agregador/plugin — aqui só roteia."""
    settings = get_settings()
    return await _dispatch(name, args, settings, store)
