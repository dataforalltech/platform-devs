"""Servidor MCP do pipeline — sidecar kind=mcp_http, GATEWAY-READY (Model C).

Reescrito para o padrão canônico do platform-service-template (v2.0). Implementa o
contrato de integração com o MCP Gateway central (platform-mcp-gateway):
  - docs/standards/STD-MCP-001-mcp-gateway-integration-contract.md  (CI-1..CI-11)
  - docs/standards/STD-SEC-006-token-model-c-inner-token.md          (inner token / audiência)

Pontos gateway-ready:
  1. /mcp/tools/list emite, por tool, inputSchema type=object + capability +
     required_scope + resource_type + data_domain (o gateway NÃO deriva por nome).
  2. /mcp/tools/call re-verifica o **inner Twin Token** (aud=mcp:pipeline-mcp) via
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

NOTA: pipeline-mcp é stateful — mantém pipelines/gates/promoções num PostgreSQL via
`PipelineStore` e chama a GitHub REST API para criar/mergiar PRs. Não há um Trinity
backend HTTP intermediário, então não há ServiceApiClient; o dispatcher recebe o store.

Regras de aprovação:
  DEV  (PRs → develop):     pipeline-mcp auto-aprova e mergia autonomamente
  HML  (develop → homol):   pipeline-mcp cria PR, aguarda aprovação humana
  PROD (homol → main):      pipeline-mcp cria PR, aguarda aprovação humana

Tools:
  Pipeline (8):  register_pipeline, get_pipeline, list_pipeline,
                 promote_service, approve_promotion, watch_prs,
                 block_service, rollback
  Gates (3):     add_gate_result, get_gate_status, clear_gates
  History (3):   get_promotion_history, get_pipeline_overview, set_pipeline_config
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
from ..config.settings import PipelineSettings, get_settings
from ..db.schema import ensure_schema
from ..db.store import PipelineStore
from ..tools import (
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

_log = logging.getLogger(__name__)

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

# Health/status são encaminhadas SEM inner token (CI-7 exempt_tools — só tokenless).
# pipeline-mcp não expõe tool tokenless: TODAS as tools tocam estado/GitHub e exigem
# inner token válido (fail-closed). O liveness fica no endpoint /v1/health (sem tool).
_EXEMPT_TOOLS: frozenset[str] = frozenset()
# Denylist fail-safe: tools que retornam segredos NUNCA saem pelo gateway (CI-7).
_EXCLUDE_TOOLS: frozenset[str] = frozenset()

# Campos de policy repassados no /mcp/tools/list (o gateway lê estes campos).
_POLICY_FIELDS = ("capability", "required_scope", "resource_type", "data_domain")


# ── Verificação do inner Twin Token (STD-SEC-006 / CI-4/CI-5) ─────────────────


def _verify_inner_token(twin_token: str, settings: PipelineSettings) -> dict[str, Any]:
    """Re-verifica o inner Twin Token na PRÓPRIA audiência (mcp:pipeline-mcp).

    O gateway já verificou o front token; o backend é 'one more verified client'
    (defense in depth). RS256 via JWKS do platform-admin; audiência exata; jti
    obrigatório. Levanta em qualquer falha (fail-closed).
    """
    if not settings.mcp_twin_audience or not settings.url_admin_twin_jwks:
        raise PermissionError(
            "integração com o gateway não configurada: defina MCP_TWIN_AUDIENCE "
            "(mcp:pipeline-mcp) e URL_ADMIN_TWIN_JWKS (ver STD-SEC-006 / IT-006)."
        )
    signing_key = jwt.PyJWKClient(settings.url_admin_twin_jwks).get_signing_key_from_jwt(twin_token)
    return jwt.decode(
        twin_token,
        signing_key.key,
        algorithms=["RS256"],  # RS256 exclusivo (STD-SEC-001)
        audience=settings.mcp_twin_audience,  # a falha de integração nº 1
        options={"require": ["exp", "aud", "jti"]},  # sem jti → rejeita (JTI_REQUIRED)
    )


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


# ── Tenant plumbing (credencial-zero) ─────────────────────────────────────────
# Bootstrap de schema roda UMA vez por tenant/processo (idempotente de qualquer forma).
_SCHEMA_READY: set[str] = set()
_SCHEMA_LOCK = asyncio.Lock()


async def _ensure_tenant_schema(settings: PipelineSettings, tenant_id: str) -> None:
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


async def _run_tool(
    name: str, arguments: dict[str, Any], settings: PipelineSettings, tenant_id: str
) -> dict[str, Any]:
    """Abre a sessão tenant-scoped (credencial-zero), garante o schema e despacha."""
    await _ensure_tenant_schema(settings, tenant_id)
    async with for_tenant(tenant_id) as session:
        store = PipelineStore(session)
        return await _dispatch(name, arguments, settings, store)


# ── HTTP Sidecar ──────────────────────────────────────────────────────────────


def _build_http_app(settings: PipelineSettings) -> FastAPI:
    """Cria o sidecar HTTP (health + bridge governado /mcp/tools/*).

    Stateless quanto a store: cada chamada abre uma sessão tenant-scoped
    (credencial-zero) a partir do tenant nos claims do inner token."""
    app = FastAPI(
        title="pipeline-mcp API",
        version="0.1.0",
        docs_url="/docs" if settings.docs_enabled else None,  # false em todo ambiente
        redoc_url=None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
    )

    @app.get("/v1/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "service": "pipeline-mcp", "tools": len(_TOOL_SCHEMAS)}

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
    async def http_call_tool(body: dict) -> Any:
        params = body.get("params", body)
        name = params.get("name", "")
        arguments = dict(params.get("arguments", {}) or {})

        if name in _EXCLUDE_TOOLS:
            return JSONResponse(status_code=403, content={"error": "tool_excluded", "tool": name})

        # Toda tool do pipeline toca estado do tenant → inner token obrigatório (não há
        # _EXEMPT_TOOLS). O tenant vem SEMPRE dos claims (SEC-035 / INV-3), nunca do arg.
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

        try:
            payload = await _run_tool(name, arguments, settings, str(tenant_id))
        except KeyError:
            return JSONResponse(status_code=404, content={"error": "unknown_tool", "tool": name})
        except Exception as exc:  # noqa: BLE001 — a resposta carrega o erro
            _log.exception("tool_internal_error: %s", name)
            payload = {"error": "internal_error", "detail": str(exc), "tool": name}
        content = [TextContent(type="text", text=json.dumps(payload, ensure_ascii=False, indent=2))]
        return {"result": {"content": [c.model_dump(exclude_none=True) for c in content]}}

    @app.on_event("shutdown")
    async def _close_pools() -> None:
        # Fecha os pools por-tenant no shutdown (registry compartilhado da lib).
        await close_tenant_pools()

    return app


# ── Server (stdio + sidecar) ──────────────────────────────────────────────────


def build_server() -> tuple[Any, PipelineSettings, FastAPI]:
    """Inicializa o MCP Server (stdio), settings e o sidecar HTTP.

    Não há mais store global: a persistência é tenant-scoped e resolvida por-request
    (credencial-zero). ``orm.configure(settings)`` registra a fonte admin (ADMIN_DB_*)
    usada para resolver o tenant → credencial do seu banco via PLATFORMS."""
    settings = get_settings()
    settings.enforce_security_invariants()  # fail-fast STD-SEC-001/004/006
    configure_logging(settings)  # logging estruturado JSON (STD-OBS-001)
    configure(settings)  # bootstrap credencial-zero (ORM-H-12): admin source p/ for_tenant
    http_app = _build_http_app(settings)
    _log.info("pipeline_mcp_ready tools=%d engine=%s", len(_TOOL_SCHEMAS), settings.DB_ENGINE)

    server: Server = Server("pipeline-mcp-server")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(name=name, description=meta["description"], inputSchema=meta["schema"])
            for name, meta in _TOOL_SCHEMAS.items()
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any] | None) -> list[TextContent]:
        # O transporte stdio não carrega o inner token (logo, sem tenant). pipeline-mcp
        # é gateway-only: a execução real entra pelo sidecar HTTP (/mcp/tools/call), onde
        # o tenant vem dos claims verificados. Aqui recusamos fail-closed (sem tenant).
        if name not in _TOOL_SCHEMAS:
            payload: dict[str, Any] = {"error": "unknown_tool", "tool": name}
        else:
            payload = {
                "error": "tenant_context_required",
                "tool": name,
                "detail": (
                    "pipeline-mcp é tenant-scoped e gateway-only; chame via o sidecar HTTP "
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
