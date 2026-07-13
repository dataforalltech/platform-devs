"""Servidor MCP do product-manager — sidecar kind=mcp_http, GATEWAY-READY (Model C).

Implementa o contrato de integração com o MCP Gateway central (platform-mcp-gateway):
  - docs/standards/STD-MCP-001-mcp-gateway-integration-contract.md  (CI-1..CI-11)
  - docs/standards/STD-SEC-006-token-model-c-inner-token.md          (inner token / audiência)

Pontos gateway-ready:
  1. /mcp/tools/list emite, por tool, inputSchema type=object + capability +
     required_scope + resource_type + data_domain (o gateway NÃO deriva por nome).
  2. /mcp/tools/call re-verifica o **inner Twin Token** (aud=mcp:product-manager-mcp) via
     JWKS do platform-admin, na PRÓPRIA audiência (defense in depth — CI-4/CI-5). O
     inner token chega em params._meta.twin_token.
  3. tenant_id vem SEMPRE dos claims do token verificado — nunca de argumento do
     cliente (SEC-035 / INV-3).
  4. _EXEMPT_TOOLS (tokenless) e _EXCLUDE_TOOLS (denylist fail-safe).
  5. /docs desabilitado (DOCS_ENABLED=false — HTTP-01).

Transporte: stdio (primário, MCP) + sidecar HTTP (:MCP_PORT):
  GET  /v1/health        — liveness (health_path do registro, sem token)
  GET  /mcp/tools/list   — catálogo governado (com metadados de policy)
  POST /mcp/tools/call   — execução (inner token obrigatório, exceto _EXEMPT_TOOLS)

NOTA: product-manager-mcp é stateful — "o agente gera o conteúdo, a tool persiste": as
tools persistem feature specs/GTM briefs/release plans/visões/artefatos num MySQL via
`ProductManagerStore` (tenant-scoped, dual-db, credencial-zero). Não há backend REST
intermediário; o dispatcher recebe o store já ligado ao pool do tenant.
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
from ..config.settings import ProductManagerSettings, get_settings
from ..db.schema import ensure_schema
from ..db.store import ProductManagerStore
from ..tools import (
    delete_artifact,
    delete_feature_spec,
    delete_gtm_brief,
    delete_product_vision,
    delete_release_plan,
    get_artifact,
    get_feature_spec,
    get_gtm_brief,
    get_product_vision,
    get_release_plan,
    list_artifacts,
    list_feature_specs,
    list_gtm_briefs,
    list_product_visions,
    list_release_plans,
    save_artifact,
    save_feature_spec,
    save_gtm_brief,
    save_release_plan,
    set_product_vision,
    update_feature_spec,
    update_gtm_brief,
    update_release_plan,
)

_log = logging.getLogger(__name__)

# ── Tool Schemas + Policy metadata (STD-MCP-001 CI-2) ─────────────────────────
# Cada tool declara description/schema + os 4 campos de política:
#   capability     — id estável <namespace>.<tool> (não derivar por nome no gateway)
#   required_scope — escopo <namespace>:<resource_type>:<acao> (least-privilege)
#   resource_type  — tipo de recurso tocado
#   data_domain    — domínio de dado (governa HITL floor / classificação LGPD)
# inputSchema MUST ser type=object com properties. Consultas (list/get) usam :read;
# mutações (save/set/update/delete) usam :write.
# ─────────────────────────────────────────────────────────────────────────────
_STR = {"type": "string"}
_INT = {"type": "integer"}
_NUM = {"type": "number"}
_OBJ = {"type": "object"}
_ARR = {"type": "array"}


def _schema(props: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    s: dict[str, Any] = {"type": "object", "additionalProperties": False, "properties": props}
    if required:
        s["required"] = required
    return s


def _meta(cap: str, scope: str, rtype: str, domain: str, desc: str, schema: dict[str, Any]) -> dict[str, Any]:
    return {
        "description": desc,
        "capability": f"product-manager-mcp.{cap}",
        "required_scope": f"product-manager-mcp:{scope}",
        "resource_type": rtype,
        "data_domain": domain,
        "schema": schema,
    }


_TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    # ── Feature Specs ──────────────────────────────────────────────────────── #
    "save_feature_spec": _meta(
        "save_feature_spec",
        "feature_spec:write",
        "feature_spec",
        "product-manager",
        "Persiste uma feature spec fornecida pelo agente (o conteúdo vem do agente).",
        _schema(
            {
                "feature": dict(_STR, description="Funcionalidade/tema alvo."),
                "content": dict(_OBJ, description="Conteúdo da spec (user_stories/acceptance_criteria/...)."),
                "objective": dict(_STR, description="Objetivo da feature (opcional)."),
                "priority": dict(_STR, description="Prioridade (high/medium/low; opcional)."),
                "status": dict(_STR, description="Status da spec (opcional)."),
            },
            required=["feature", "content"],
        ),
    ),
    "list_feature_specs": _meta(
        "list_feature_specs",
        "feature_spec:read",
        "feature_spec",
        "product-manager",
        "Lista feature specs persistidas, com filtros opcionais.",
        _schema(
            {
                "feature": dict(_STR, description="Filtrar por funcionalidade (opcional)."),
                "status": dict(_STR, description="Filtrar por status (opcional)."),
            }
        ),
    ),
    "get_feature_spec": _meta(
        "get_feature_spec",
        "feature_spec:read",
        "feature_spec",
        "product-manager",
        "Retorna uma feature spec por id.",
        _schema({"id": dict(_INT, description="Id da spec.")}, required=["id"]),
    ),
    "update_feature_spec": _meta(
        "update_feature_spec",
        "feature_spec:write",
        "feature_spec",
        "product-manager",
        "Atualiza campos mutáveis de uma feature spec (objective/priority/content/status).",
        _schema(
            {
                "id": dict(_INT, description="Id da spec."),
                "objective": dict(_STR, description="Novo objetivo (opcional)."),
                "priority": dict(_STR, description="Nova prioridade (opcional)."),
                "content": dict(_OBJ, description="Novo conteúdo (opcional)."),
                "status": dict(_STR, description="Novo status (opcional)."),
            },
            required=["id"],
        ),
    ),
    "delete_feature_spec": _meta(
        "delete_feature_spec",
        "feature_spec:write",
        "feature_spec",
        "product-manager",
        "Soft-delete de uma feature spec por id.",
        _schema({"id": dict(_INT, description="Id da spec.")}, required=["id"]),
    ),
    # ── GTM Briefs ─────────────────────────────────────────────────────────── #
    "save_gtm_brief": _meta(
        "save_gtm_brief",
        "gtm_brief:write",
        "gtm_brief",
        "product-manager",
        "Persiste um go-to-market brief fornecido pelo agente (o conteúdo vem do agente).",
        _schema(
            {
                "product": dict(_STR, description="Produto/lançamento alvo."),
                "content": dict(
                    _OBJ, description="Conteúdo do brief (target_segment/key_messages/channels/...)."
                ),
                "launch_timing": dict(_STR, description="Janela de lançamento (ex.: 'Q2 2026'; opcional)."),
                "status": dict(_STR, description="Status do brief (opcional)."),
            },
            required=["product", "content"],
        ),
    ),
    "list_gtm_briefs": _meta(
        "list_gtm_briefs",
        "gtm_brief:read",
        "gtm_brief",
        "product-manager",
        "Lista GTM briefs persistidos, com filtros opcionais.",
        _schema(
            {
                "product": dict(_STR, description="Filtrar por produto (opcional)."),
                "status": dict(_STR, description="Filtrar por status (opcional)."),
            }
        ),
    ),
    "get_gtm_brief": _meta(
        "get_gtm_brief",
        "gtm_brief:read",
        "gtm_brief",
        "product-manager",
        "Retorna um GTM brief por id.",
        _schema({"id": dict(_INT, description="Id do brief.")}, required=["id"]),
    ),
    "update_gtm_brief": _meta(
        "update_gtm_brief",
        "gtm_brief:write",
        "gtm_brief",
        "product-manager",
        "Atualiza campos mutáveis de um GTM brief (launch_timing/content/status).",
        _schema(
            {
                "id": dict(_INT, description="Id do brief."),
                "launch_timing": dict(_STR, description="Nova janela de lançamento (opcional)."),
                "content": dict(_OBJ, description="Novo conteúdo (opcional)."),
                "status": dict(_STR, description="Novo status (opcional)."),
            },
            required=["id"],
        ),
    ),
    "delete_gtm_brief": _meta(
        "delete_gtm_brief",
        "gtm_brief:write",
        "gtm_brief",
        "product-manager",
        "Soft-delete de um GTM brief por id.",
        _schema({"id": dict(_INT, description="Id do brief.")}, required=["id"]),
    ),
    # ── Release Plans ──────────────────────────────────────────────────────── #
    "save_release_plan": _meta(
        "save_release_plan",
        "release_plan:write",
        "release_plan",
        "product-manager",
        "Persiste um plano de release fornecido pelo agente (o conteúdo vem do agente).",
        _schema(
            {
                "product": dict(_STR, description="Produto alvo."),
                "content": dict(_OBJ, description="Conteúdo do plano (phases/timeline/features_per_phase)."),
                "status": dict(_STR, description="Status do plano (opcional)."),
            },
            required=["product", "content"],
        ),
    ),
    "list_release_plans": _meta(
        "list_release_plans",
        "release_plan:read",
        "release_plan",
        "product-manager",
        "Lista planos de release persistidos, com filtros opcionais.",
        _schema(
            {
                "product": dict(_STR, description="Filtrar por produto (opcional)."),
                "status": dict(_STR, description="Filtrar por status (opcional)."),
            }
        ),
    ),
    "get_release_plan": _meta(
        "get_release_plan",
        "release_plan:read",
        "release_plan",
        "product-manager",
        "Retorna um plano de release por id.",
        _schema({"id": dict(_INT, description="Id do plano.")}, required=["id"]),
    ),
    "update_release_plan": _meta(
        "update_release_plan",
        "release_plan:write",
        "release_plan",
        "product-manager",
        "Atualiza campos mutáveis de um plano de release (content/status).",
        _schema(
            {
                "id": dict(_INT, description="Id do plano."),
                "content": dict(_OBJ, description="Novo conteúdo (opcional)."),
                "status": dict(_STR, description="Novo status (opcional)."),
            },
            required=["id"],
        ),
    ),
    "delete_release_plan": _meta(
        "delete_release_plan",
        "release_plan:write",
        "release_plan",
        "product-manager",
        "Soft-delete de um plano de release por id.",
        _schema({"id": dict(_INT, description="Id do plano.")}, required=["id"]),
    ),
    # ── Product Visions (upsert por product) ───────────────────────────────── #
    "set_product_vision": _meta(
        "set_product_vision",
        "product_vision:write",
        "product_vision",
        "product-manager",
        "Define (upsert) a visão de um produto (vision/mission/goals fornecidos pelo agente).",
        _schema(
            {
                "product": dict(_STR, description="Produto alvo (chave natural única)."),
                "vision": dict(_STR, description="Declaração de visão (opcional)."),
                "mission": dict(_STR, description="Declaração de missão (opcional)."),
                "goals": dict(_ARR, description="Objetivos do produto (lista; opcional)."),
                "status": dict(_STR, description="Status da visão (opcional)."),
            },
            required=["product"],
        ),
    ),
    "list_product_visions": _meta(
        "list_product_visions",
        "product_vision:read",
        "product_vision",
        "product-manager",
        "Lista visões de produto persistidas, com filtro opcional por status.",
        _schema({"status": dict(_STR, description="Filtrar por status (opcional).")}),
    ),
    "get_product_vision": _meta(
        "get_product_vision",
        "product_vision:read",
        "product_vision",
        "product-manager",
        "Retorna a visão de um produto.",
        _schema({"product": dict(_STR, description="Produto alvo.")}, required=["product"]),
    ),
    "delete_product_vision": _meta(
        "delete_product_vision",
        "product_vision:write",
        "product_vision",
        "product-manager",
        "Soft-delete da visão de um produto.",
        _schema({"product": dict(_STR, description="Produto alvo.")}, required=["product"]),
    ),
    # ── Artifacts (histórico append-only) ──────────────────────────────────── #
    "save_artifact": _meta(
        "save_artifact",
        "artifact:write",
        "artifact",
        "product-manager",
        "Persiste um artefato de produto (documento/texto) gerado pelo agente.",
        _schema(
            {
                "kind": dict(
                    _STR,
                    description=(
                        "Tipo: product_vision|feature_spec|gtm_brief|release_plan|roadmap|"
                        "prd|okr|persona|user_story|discovery|analysis."
                    ),
                ),
                "target": dict(_STR, description="Alvo (produto/feature/segmento)."),
                "content": dict(_STR, description="Documento/texto gerado pelo agente."),
                "fmt": dict(_STR, description="Formato (markdown/json/...; opcional)."),
                "meta": dict(_OBJ, description="Metadados adicionais (opcional)."),
            },
            required=["kind", "target", "content"],
        ),
    ),
    "list_artifacts": _meta(
        "list_artifacts",
        "artifact:read",
        "artifact",
        "product-manager",
        "Lista artefatos persistidos, com filtros opcionais.",
        _schema(
            {
                "kind": dict(_STR, description="Filtrar por tipo (opcional)."),
                "target": dict(_STR, description="Filtrar por alvo (opcional)."),
                "limit": dict(_INT, description="Máximo de registros (default 50)."),
            }
        ),
    ),
    "get_artifact": _meta(
        "get_artifact",
        "artifact:read",
        "artifact",
        "product-manager",
        "Retorna um artefato por id.",
        _schema({"id": dict(_INT, description="Id do artefato.")}, required=["id"]),
    ),
    "delete_artifact": _meta(
        "delete_artifact",
        "artifact:write",
        "artifact",
        "product-manager",
        "Soft-delete de um artefato por id.",
        _schema({"id": dict(_INT, description="Id do artefato.")}, required=["id"]),
    ),
}

# product-manager-mcp não expõe tool tokenless: TODAS as tools tocam estado do tenant e
# exigem inner token válido (fail-closed). O liveness fica no /v1/health (sem tool).
_EXEMPT_TOOLS: frozenset[str] = frozenset()
# Denylist fail-safe: tools que retornam segredos NUNCA saem pelo gateway (CI-7).
_EXCLUDE_TOOLS: frozenset[str] = frozenset()

# Campos de policy repassados no /mcp/tools/list (o gateway lê estes campos).
_POLICY_FIELDS = ("capability", "required_scope", "resource_type", "data_domain")


# ── Verificação do inner Twin Token (STD-SEC-006 / CI-4/CI-5) ─────────────────


def _verify_inner_token(twin_token: str, settings: ProductManagerSettings) -> dict[str, Any]:
    """Re-verifica o inner Twin Token na PRÓPRIA audiência (mcp:product-manager-mcp).

    O gateway já verificou o front token; o backend é 'one more verified client'
    (defense in depth). RS256 via JWKS do platform-admin; audiência exata; jti
    obrigatório. Levanta em qualquer falha (fail-closed).
    """
    if not settings.mcp_twin_audience or not settings.url_admin_twin_jwks:
        raise PermissionError(
            "integração com o gateway não configurada: defina MCP_TWIN_AUDIENCE "
            "(mcp:product-manager-mcp) e URL_ADMIN_TWIN_JWKS (ver STD-SEC-006 / IT-006)."
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


async def _dispatch(name: str, args: dict[str, Any], store: ProductManagerStore) -> dict[str, Any]:
    """Despacha a chamada para a tool (async). O tenant NÃO viaja nos args (INV-3):
    o ``store`` já está ligado ao pool do tenant (resolvido dos claims do inner token)."""
    # ── Feature Specs ──────────────────────────────────────────────────────── #
    if name == "save_feature_spec":
        return await save_feature_spec(
            store,
            feature=args["feature"],
            content=args["content"],
            objective=args.get("objective"),
            priority=args.get("priority"),
            status=args.get("status"),
        )
    if name == "list_feature_specs":
        return await list_feature_specs(store, feature=args.get("feature"), status=args.get("status"))
    if name == "get_feature_spec":
        return await get_feature_spec(store, spec_id=args["id"])
    if name == "update_feature_spec":
        return await update_feature_spec(
            store,
            spec_id=args["id"],
            objective=args.get("objective"),
            priority=args.get("priority"),
            content=args.get("content"),
            status=args.get("status"),
        )
    if name == "delete_feature_spec":
        return await delete_feature_spec(store, spec_id=args["id"])
    # ── GTM Briefs ─────────────────────────────────────────────────────────── #
    if name == "save_gtm_brief":
        return await save_gtm_brief(
            store,
            product=args["product"],
            content=args["content"],
            launch_timing=args.get("launch_timing"),
            status=args.get("status"),
        )
    if name == "list_gtm_briefs":
        return await list_gtm_briefs(store, product=args.get("product"), status=args.get("status"))
    if name == "get_gtm_brief":
        return await get_gtm_brief(store, brief_id=args["id"])
    if name == "update_gtm_brief":
        return await update_gtm_brief(
            store,
            brief_id=args["id"],
            launch_timing=args.get("launch_timing"),
            content=args.get("content"),
            status=args.get("status"),
        )
    if name == "delete_gtm_brief":
        return await delete_gtm_brief(store, brief_id=args["id"])
    # ── Release Plans ──────────────────────────────────────────────────────── #
    if name == "save_release_plan":
        return await save_release_plan(
            store,
            product=args["product"],
            content=args["content"],
            status=args.get("status"),
        )
    if name == "list_release_plans":
        return await list_release_plans(store, product=args.get("product"), status=args.get("status"))
    if name == "get_release_plan":
        return await get_release_plan(store, plan_id=args["id"])
    if name == "update_release_plan":
        return await update_release_plan(
            store,
            plan_id=args["id"],
            content=args.get("content"),
            status=args.get("status"),
        )
    if name == "delete_release_plan":
        return await delete_release_plan(store, plan_id=args["id"])
    # ── Product Visions (upsert por product) ───────────────────────────────── #
    if name == "set_product_vision":
        return await set_product_vision(
            store,
            product=args["product"],
            vision=args.get("vision"),
            mission=args.get("mission"),
            goals=args.get("goals"),
            status=args.get("status"),
        )
    if name == "list_product_visions":
        return await list_product_visions(store, status=args.get("status"))
    if name == "get_product_vision":
        return await get_product_vision(store, product=args["product"])
    if name == "delete_product_vision":
        return await delete_product_vision(store, product=args["product"])
    # ── Artifacts ──────────────────────────────────────────────────────────── #
    if name == "save_artifact":
        return await save_artifact(
            store,
            kind=args["kind"],
            target=args["target"],
            content=args["content"],
            fmt=args.get("fmt"),
            meta=args.get("meta"),
        )
    if name == "list_artifacts":
        return await list_artifacts(
            store, kind=args.get("kind"), target=args.get("target"), limit=args.get("limit", 50)
        )
    if name == "get_artifact":
        return await get_artifact(store, artifact_id=args["id"])
    if name == "delete_artifact":
        return await delete_artifact(store, artifact_id=args["id"])
    raise KeyError(name)


# ── Tenant plumbing (credencial-zero) ─────────────────────────────────────────
# Bootstrap de schema roda UMA vez por tenant/processo (idempotente de qualquer forma).
_SCHEMA_READY: set[str] = set()
_SCHEMA_LOCK = asyncio.Lock()


async def _ensure_tenant_schema(settings: ProductManagerSettings, tenant_id: str) -> None:
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
    name: str, arguments: dict[str, Any], settings: ProductManagerSettings, tenant_id: str
) -> dict[str, Any]:
    """Abre a sessão tenant-scoped (credencial-zero), garante o schema e despacha."""
    await _ensure_tenant_schema(settings, tenant_id)
    async with for_tenant(tenant_id) as session:
        store = ProductManagerStore(session)
        return await _dispatch(name, arguments, store)


# ── HTTP Sidecar ──────────────────────────────────────────────────────────────


def _build_http_app(settings: ProductManagerSettings) -> FastAPI:
    """Cria o sidecar HTTP (health + bridge governado /mcp/tools/*).

    Stateless quanto a store: cada chamada abre uma sessão tenant-scoped
    (credencial-zero) a partir do tenant nos claims do inner token."""
    app = FastAPI(
        title="product-manager-mcp API",
        version="0.1.0",
        docs_url="/docs" if settings.docs_enabled else None,  # false em todo ambiente
        redoc_url=None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
    )

    @app.get("/v1/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "service": "product-manager-mcp", "tools": len(_TOOL_SCHEMAS)}

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

        # Toda tool do product-manager toca estado do tenant → inner token obrigatório (não há
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


def build_server() -> tuple[Any, ProductManagerSettings, FastAPI]:
    """Inicializa o MCP Server (stdio), settings e o sidecar HTTP.

    A persistência é tenant-scoped e resolvida por-request (credencial-zero).
    ``orm.configure(settings)`` registra a fonte admin (ADMIN_DB_*) usada para
    resolver o tenant → credencial do seu banco via PLATFORMS."""
    settings = get_settings()
    settings.enforce_security_invariants()  # fail-fast STD-SEC-001/004/006
    configure_logging(settings)  # logging estruturado JSON (STD-OBS-001)
    configure(settings)  # bootstrap credencial-zero (ORM-H-12): admin source p/ for_tenant
    http_app = _build_http_app(settings)
    _log.info("product_manager_mcp_ready tools=%d engine=%s", len(_TOOL_SCHEMAS), settings.DB_ENGINE)

    server: Server = Server("product-manager-mcp-server")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(name=name, description=meta["description"], inputSchema=meta["schema"])
            for name, meta in _TOOL_SCHEMAS.items()
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any] | None) -> list[TextContent]:
        # O transporte stdio não carrega o inner token (logo, sem tenant). product-manager-mcp
        # é gateway-only: a execução real entra pelo sidecar HTTP (/mcp/tools/call), onde
        # o tenant vem dos claims verificados. Aqui recusamos fail-closed (sem tenant).
        if name not in _TOOL_SCHEMAS:
            payload: dict[str, Any] = {"error": "unknown_tool", "tool": name}
        else:
            payload = {
                "error": "tenant_context_required",
                "tool": name,
                "detail": (
                    "product-manager-mcp é tenant-scoped e gateway-only; chame via o sidecar HTTP "
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
