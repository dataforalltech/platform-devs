"""Servidor MCP do product-owner — sidecar kind=mcp_http, GATEWAY-READY (Model C).

Implementa o contrato de integração com o MCP Gateway central (platform-mcp-gateway):
  - docs/standards/STD-MCP-001-mcp-gateway-integration-contract.md  (CI-1..CI-11)
  - docs/standards/STD-SEC-006-token-model-c-inner-token.md          (inner token / audiência)

Pontos gateway-ready:
  1. /mcp/tools/list emite, por tool, inputSchema type=object + capability +
     required_scope + resource_type + data_domain (o gateway NÃO deriva por nome).
  2. /mcp/tools/call re-verifica o **inner Twin Token** (aud=mcp:product-owner-mcp) via
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

NOTA: product-owner-mcp é stateful — "o agente gera o conteúdo, a tool persiste": as
tools persistem user stories/escopos de MVP/visões/personas/itens de backlog/artefatos
num MySQL via `ProductOwnerStore` (tenant-scoped, dual-db, credencial-zero). Não há
backend REST intermediário; o dispatcher recebe o store já ligado ao pool do tenant.
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
from ..config.settings import ProductOwnerSettings, get_settings
from ..db.schema import ensure_schema
from ..db.store import ProductOwnerStore
from ..tools import (
    delete_backlog_item,
    delete_mvp_scope,
    delete_po_artifact,
    delete_product_vision,
    delete_user_persona,
    delete_user_story,
    get_backlog_item,
    get_mvp_scope,
    get_po_artifact,
    get_product_vision,
    get_user_persona,
    get_user_story,
    list_backlog_items,
    list_mvp_scopes,
    list_po_artifacts,
    list_product_visions,
    list_user_personas,
    list_user_stories,
    save_backlog_item,
    save_po_artifact,
    save_user_persona,
    save_user_story,
    set_mvp_scope,
    set_product_vision,
    update_backlog_item,
    update_user_persona,
    update_user_story,
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
        "capability": f"product-owner-mcp.{cap}",
        "required_scope": f"product-owner-mcp:{scope}",
        "resource_type": rtype,
        "data_domain": domain,
        "schema": schema,
    }


_TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    # ── User Stories ───────────────────────────────────────────────────────── #
    "save_user_story": _meta(
        "save_user_story",
        "user_story:write",
        "user_story",
        "product-owner",
        "Persiste uma user story fornecida pelo agente (o conteúdo vem do agente).",
        _schema(
            {
                "feature": dict(_STR, description="Feature/épico alvo."),
                "role": dict(_STR, description="Papel/persona da história."),
                "goal": dict(_STR, description="Objetivo/ação desejada (opcional)."),
                "benefit": dict(_STR, description="Benefício/valor esperado (opcional)."),
                "story": dict(_STR, description="Sentença 'As a ... I want ... so that ...' (opcional)."),
                "acceptance_criteria": dict(_ARR, description="Critérios de aceite (lista, opcional)."),
                "priority": dict(_STR, description="Prioridade (opcional)."),
                "status": dict(_STR, description="Status (opcional)."),
            },
            required=["feature", "role"],
        ),
    ),
    "list_user_stories": _meta(
        "list_user_stories",
        "user_story:read",
        "user_story",
        "product-owner",
        "Lista user stories persistidas, com filtros opcionais.",
        _schema(
            {
                "feature": dict(_STR, description="Filtrar por feature (opcional)."),
                "role": dict(_STR, description="Filtrar por papel (opcional)."),
                "status": dict(_STR, description="Filtrar por status (opcional)."),
            }
        ),
    ),
    "get_user_story": _meta(
        "get_user_story",
        "user_story:read",
        "user_story",
        "product-owner",
        "Retorna uma user story persistida (papel, objetivo, benefício, critérios de aceite) por id.",
        _schema({"id": dict(_INT, description="Id da história.")}, required=["id"]),
    ),
    "update_user_story": _meta(
        "update_user_story",
        "user_story:write",
        "user_story",
        "product-owner",
        "Atualiza campos mutáveis de uma user story.",
        _schema(
            {
                "id": dict(_INT, description="Id da história."),
                "role": dict(_STR, description="Novo papel (opcional)."),
                "goal": dict(_STR, description="Novo objetivo (opcional)."),
                "benefit": dict(_STR, description="Novo benefício (opcional)."),
                "story": dict(_STR, description="Nova sentença (opcional)."),
                "acceptance_criteria": dict(_ARR, description="Novos critérios de aceite (opcional)."),
                "priority": dict(_STR, description="Nova prioridade (opcional)."),
                "status": dict(_STR, description="Novo status (opcional)."),
            },
            required=["id"],
        ),
    ),
    "delete_user_story": _meta(
        "delete_user_story",
        "user_story:write",
        "user_story",
        "product-owner",
        "Remove (soft-delete) uma user story persistida por id; informa deleted e deleted_count.",
        _schema({"id": dict(_INT, description="Id da história.")}, required=["id"]),
    ),
    # ── MVP Scopes (upsert por product) ────────────────────────────────────── #
    "set_mvp_scope": _meta(
        "set_mvp_scope",
        "mvp_scope:write",
        "mvp_scope",
        "product-owner",
        "Define (upsert) o escopo de MVP de um produto com o recorte fornecido.",
        _schema(
            {
                "product": dict(_STR, description="Produto alvo (chave natural única)."),
                "content": dict(_OBJ, description="Recorte do MVP (core/should/could/out_of_scope)."),
                "goal": dict(_STR, description="Objetivo do MVP (opcional)."),
                "status": dict(_STR, description="Status (opcional)."),
            },
            required=["product", "content"],
        ),
    ),
    "list_mvp_scopes": _meta(
        "list_mvp_scopes",
        "mvp_scope:read",
        "mvp_scope",
        "product-owner",
        "Lista escopos de MVP persistidos, com filtro opcional por status.",
        _schema({"status": dict(_STR, description="Filtrar por status (opcional).")}),
    ),
    "get_mvp_scope": _meta(
        "get_mvp_scope",
        "mvp_scope:read",
        "mvp_scope",
        "product-owner",
        "Retorna o escopo de MVP persistido (core/should/could/out_of_scope) de um produto pela chave product.",
        _schema({"product": dict(_STR, description="Produto alvo.")}, required=["product"]),
    ),
    "delete_mvp_scope": _meta(
        "delete_mvp_scope",
        "mvp_scope:write",
        "mvp_scope",
        "product-owner",
        "Soft-delete do escopo de MVP de um produto.",
        _schema({"product": dict(_STR, description="Produto alvo.")}, required=["product"]),
    ),
    # ── Product Visions (upsert por product) ───────────────────────────────── #
    "set_product_vision": _meta(
        "set_product_vision",
        "product_vision:write",
        "product_vision",
        "product-owner",
        "Define (upsert) a visão de um produto com o conteúdo fornecido.",
        _schema(
            {
                "product": dict(_STR, description="Produto alvo (chave natural única)."),
                "vision": dict(_STR, description="Sentença de visão (opcional)."),
                "target_audience": dict(_STR, description="Público-alvo (opcional)."),
                "content": dict(
                    _OBJ, description="Conteúdo da visão (mission/goals/success_criteria/differentiator)."
                ),
                "status": dict(_STR, description="Status (opcional)."),
            },
            required=["product"],
        ),
    ),
    "list_product_visions": _meta(
        "list_product_visions",
        "product_vision:read",
        "product_vision",
        "product-owner",
        "Lista visões de produto persistidas, com filtro opcional por status.",
        _schema({"status": dict(_STR, description="Filtrar por status (opcional).")}),
    ),
    "get_product_vision": _meta(
        "get_product_vision",
        "product_vision:read",
        "product_vision",
        "product-owner",
        "Retorna a visão de produto persistida (missão, metas, público-alvo) pela chave natural product.",
        _schema({"product": dict(_STR, description="Produto alvo.")}, required=["product"]),
    ),
    "delete_product_vision": _meta(
        "delete_product_vision",
        "product_vision:write",
        "product_vision",
        "product-owner",
        "Remove (soft-delete) a visão de um produto pela chave natural product; informa deleted e deleted_count.",
        _schema({"product": dict(_STR, description="Produto alvo.")}, required=["product"]),
    ),
    # ── User Personas ──────────────────────────────────────────────────────── #
    "save_user_persona": _meta(
        "save_user_persona",
        "user_persona:write",
        "user_persona",
        "product-owner",
        "Persiste uma persona de usuário fornecida pelo agente.",
        _schema(
            {
                "name": dict(_STR, description="Nome da persona."),
                "segment": dict(_STR, description="Segmento (opcional)."),
                "demographics": dict(_OBJ, description="Mapa demográfico (opcional)."),
                "goals": dict(_ARR, description="Objetivos (lista, opcional)."),
                "pains": dict(_ARR, description="Dores (lista, opcional)."),
                "behaviors": dict(_ARR, description="Comportamentos (lista, opcional)."),
            },
            required=["name"],
        ),
    ),
    "list_user_personas": _meta(
        "list_user_personas",
        "user_persona:read",
        "user_persona",
        "product-owner",
        "Lista personas persistidas, com filtros opcionais.",
        _schema(
            {
                "segment": dict(_STR, description="Filtrar por segmento (opcional)."),
                "name": dict(_STR, description="Filtrar por nome (opcional)."),
            }
        ),
    ),
    "get_user_persona": _meta(
        "get_user_persona",
        "user_persona:read",
        "user_persona",
        "product-owner",
        "Retorna uma persona de usuário persistida (segmento, objetivos, dores, comportamentos) por id.",
        _schema({"id": dict(_INT, description="Id da persona.")}, required=["id"]),
    ),
    "update_user_persona": _meta(
        "update_user_persona",
        "user_persona:write",
        "user_persona",
        "product-owner",
        "Atualiza campos mutáveis de uma persona.",
        _schema(
            {
                "id": dict(_INT, description="Id da persona."),
                "segment": dict(_STR, description="Novo segmento (opcional)."),
                "demographics": dict(_OBJ, description="Novo mapa demográfico (opcional)."),
                "goals": dict(_ARR, description="Novos objetivos (opcional)."),
                "pains": dict(_ARR, description="Novas dores (opcional)."),
                "behaviors": dict(_ARR, description="Novos comportamentos (opcional)."),
            },
            required=["id"],
        ),
    ),
    "delete_user_persona": _meta(
        "delete_user_persona",
        "user_persona:write",
        "user_persona",
        "product-owner",
        "Remove (soft-delete) uma persona de usuário persistida por id; informa deleted e deleted_count.",
        _schema({"id": dict(_INT, description="Id da persona.")}, required=["id"]),
    ),
    # ── Backlog Items (score RICE determinístico dobrado no save) ──────────── #
    "save_backlog_item": _meta(
        "save_backlog_item",
        "backlog_item:write",
        "backlog_item",
        "product-owner",
        "Persiste um item de backlog. Se score não vier e os campos RICE existirem, calcula-o.",
        _schema(
            {
                "name": dict(_STR, description="Nome/título do item."),
                "framework": dict(_STR, description="Framework (RICE/ICE/MoSCoW; default RICE)."),
                "reach": dict(_NUM, description="Alcance RICE (opcional)."),
                "impact": dict(_NUM, description="Impacto RICE (opcional)."),
                "confidence": dict(_NUM, description="Confiança RICE 0-1 ou 1-100 (opcional)."),
                "effort": dict(_NUM, description="Esforço RICE (opcional)."),
                "score": dict(_NUM, description="Score (opcional; calculado se ausente)."),
                "status": dict(_STR, description="Status (opcional)."),
            },
            required=["name"],
        ),
    ),
    "list_backlog_items": _meta(
        "list_backlog_items",
        "backlog_item:read",
        "backlog_item",
        "product-owner",
        "Lista itens de backlog persistidos (ordenados por score desc), com filtros opcionais.",
        _schema(
            {
                "framework": dict(_STR, description="Filtrar por framework (opcional)."),
                "status": dict(_STR, description="Filtrar por status (opcional)."),
            }
        ),
    ),
    "get_backlog_item": _meta(
        "get_backlog_item",
        "backlog_item:read",
        "backlog_item",
        "product-owner",
        "Retorna um item de backlog persistido (framework, componentes RICE, score, status) por id.",
        _schema({"id": dict(_INT, description="Id do item.")}, required=["id"]),
    ),
    "update_backlog_item": _meta(
        "update_backlog_item",
        "backlog_item:write",
        "backlog_item",
        "product-owner",
        "Atualiza campos mutáveis de um item de backlog.",
        _schema(
            {
                "id": dict(_INT, description="Id do item."),
                "framework": dict(_STR, description="Novo framework (opcional)."),
                "reach": dict(_NUM, description="Novo alcance (opcional)."),
                "impact": dict(_NUM, description="Novo impacto (opcional)."),
                "confidence": dict(_NUM, description="Nova confiança (opcional)."),
                "effort": dict(_NUM, description="Novo esforço (opcional)."),
                "score": dict(_NUM, description="Novo score (opcional)."),
                "status": dict(_STR, description="Novo status (opcional)."),
            },
            required=["id"],
        ),
    ),
    "delete_backlog_item": _meta(
        "delete_backlog_item",
        "backlog_item:write",
        "backlog_item",
        "product-owner",
        "Soft-delete de um item de backlog por id.",
        _schema({"id": dict(_INT, description="Id do item.")}, required=["id"]),
    ),
    # ── PO Artifacts (histórico append-only) ───────────────────────────────── #
    "save_po_artifact": _meta(
        "save_po_artifact",
        "artifact:write",
        "artifact",
        "product-owner",
        "Persiste um artefato de PO (estruturado) gerado pelo agente.",
        _schema(
            {
                "kind": dict(
                    _STR,
                    description=(
                        "Tipo: journey|risks|handoff_architecture|handoff_design|"
                        "handoff_engineering|discovery|gtm|release|feature_spec|metrics|problem."
                    ),
                ),
                "target": dict(_STR, description="Alvo (feature/product/persona)."),
                "content": dict(_OBJ, description="Artefato estruturado gerado pelo agente."),
                "meta": dict(_OBJ, description="Metadados adicionais (opcional)."),
            },
            required=["kind", "target"],
        ),
    ),
    "list_po_artifacts": _meta(
        "list_po_artifacts",
        "artifact:read",
        "artifact",
        "product-owner",
        "Lista artefatos de PO persistidos, com filtros opcionais.",
        _schema(
            {
                "kind": dict(_STR, description="Filtrar por tipo (opcional)."),
                "target": dict(_STR, description="Filtrar por alvo (opcional)."),
                "limit": dict(_INT, description="Máximo de registros (default 50)."),
            }
        ),
    ),
    "get_po_artifact": _meta(
        "get_po_artifact",
        "artifact:read",
        "artifact",
        "product-owner",
        "Retorna um artefato de PO persistido (journey/handoff/discovery/release etc.) por id.",
        _schema({"id": dict(_INT, description="Id do artefato.")}, required=["id"]),
    ),
    "delete_po_artifact": _meta(
        "delete_po_artifact",
        "artifact:write",
        "artifact",
        "product-owner",
        "Soft-delete de um artefato de PO por id.",
        _schema({"id": dict(_INT, description="Id do artefato.")}, required=["id"]),
    ),
}

# product-owner-mcp não expõe tool tokenless: TODAS as tools tocam estado do tenant e
# exigem inner token válido (fail-closed). O liveness fica no /v1/health (sem tool).
_EXEMPT_TOOLS: frozenset[str] = frozenset()
# Denylist fail-safe: tools que retornam segredos NUNCA saem pelo gateway (CI-7).
_EXCLUDE_TOOLS: frozenset[str] = frozenset()

# Campos de policy repassados no /mcp/tools/list (o gateway lê estes campos).
_POLICY_FIELDS = ("capability", "required_scope", "resource_type", "data_domain")


# ── Verificação do inner Twin Token (STD-SEC-006 / CI-4/CI-5) ─────────────────


def _verify_inner_token(twin_token: str, settings: ProductOwnerSettings) -> dict[str, Any]:
    """Re-verifica o inner Twin Token na PRÓPRIA audiência (mcp:product-owner-mcp).

    O gateway já verificou o front token; o backend é 'one more verified client'
    (defense in depth). RS256 via JWKS do platform-admin; audiência exata; jti
    obrigatório. Levanta em qualquer falha (fail-closed).
    """
    if not settings.mcp_twin_audience or not settings.url_admin_twin_jwks:
        raise PermissionError(
            "integração com o gateway não configurada: defina MCP_TWIN_AUDIENCE "
            "(mcp:product-owner-mcp) e URL_ADMIN_TWIN_JWKS (ver STD-SEC-006 / IT-006)."
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


async def _dispatch(name: str, args: dict[str, Any], store: ProductOwnerStore) -> dict[str, Any]:
    """Despacha a chamada para a tool (async). O tenant NÃO viaja nos args (INV-3):
    o ``store`` já está ligado ao pool do tenant (resolvido dos claims do inner token)."""
    # ── User Stories ───────────────────────────────────────────────────────── #
    if name == "save_user_story":
        return await save_user_story(
            store,
            feature=args["feature"],
            role=args["role"],
            goal=args.get("goal"),
            benefit=args.get("benefit"),
            story=args.get("story"),
            acceptance_criteria=args.get("acceptance_criteria"),
            priority=args.get("priority"),
            status=args.get("status"),
        )
    if name == "list_user_stories":
        return await list_user_stories(
            store, feature=args.get("feature"), role=args.get("role"), status=args.get("status")
        )
    if name == "get_user_story":
        return await get_user_story(store, story_id=args["id"])
    if name == "update_user_story":
        return await update_user_story(
            store,
            story_id=args["id"],
            role=args.get("role"),
            goal=args.get("goal"),
            benefit=args.get("benefit"),
            story=args.get("story"),
            acceptance_criteria=args.get("acceptance_criteria"),
            priority=args.get("priority"),
            status=args.get("status"),
        )
    if name == "delete_user_story":
        return await delete_user_story(store, story_id=args["id"])
    # ── MVP Scopes ─────────────────────────────────────────────────────────── #
    if name == "set_mvp_scope":
        return await set_mvp_scope(
            store,
            product=args["product"],
            content=args["content"],
            goal=args.get("goal"),
            status=args.get("status"),
        )
    if name == "list_mvp_scopes":
        return await list_mvp_scopes(store, status=args.get("status"))
    if name == "get_mvp_scope":
        return await get_mvp_scope(store, product=args["product"])
    if name == "delete_mvp_scope":
        return await delete_mvp_scope(store, product=args["product"])
    # ── Product Visions ────────────────────────────────────────────────────── #
    if name == "set_product_vision":
        return await set_product_vision(
            store,
            product=args["product"],
            vision=args.get("vision"),
            target_audience=args.get("target_audience"),
            content=args.get("content"),
            status=args.get("status"),
        )
    if name == "list_product_visions":
        return await list_product_visions(store, status=args.get("status"))
    if name == "get_product_vision":
        return await get_product_vision(store, product=args["product"])
    if name == "delete_product_vision":
        return await delete_product_vision(store, product=args["product"])
    # ── User Personas ──────────────────────────────────────────────────────── #
    if name == "save_user_persona":
        return await save_user_persona(
            store,
            name=args["name"],
            segment=args.get("segment"),
            demographics=args.get("demographics"),
            goals=args.get("goals"),
            pains=args.get("pains"),
            behaviors=args.get("behaviors"),
        )
    if name == "list_user_personas":
        return await list_user_personas(store, segment=args.get("segment"), name=args.get("name"))
    if name == "get_user_persona":
        return await get_user_persona(store, persona_id=args["id"])
    if name == "update_user_persona":
        return await update_user_persona(
            store,
            persona_id=args["id"],
            segment=args.get("segment"),
            demographics=args.get("demographics"),
            goals=args.get("goals"),
            pains=args.get("pains"),
            behaviors=args.get("behaviors"),
        )
    if name == "delete_user_persona":
        return await delete_user_persona(store, persona_id=args["id"])
    # ── Backlog Items ──────────────────────────────────────────────────────── #
    if name == "save_backlog_item":
        return await save_backlog_item(
            store,
            name=args["name"],
            framework=args.get("framework", "RICE"),
            reach=args.get("reach"),
            impact=args.get("impact"),
            confidence=args.get("confidence"),
            effort=args.get("effort"),
            score=args.get("score"),
            status=args.get("status"),
        )
    if name == "list_backlog_items":
        return await list_backlog_items(store, framework=args.get("framework"), status=args.get("status"))
    if name == "get_backlog_item":
        return await get_backlog_item(store, item_id=args["id"])
    if name == "update_backlog_item":
        return await update_backlog_item(
            store,
            item_id=args["id"],
            framework=args.get("framework"),
            reach=args.get("reach"),
            impact=args.get("impact"),
            confidence=args.get("confidence"),
            effort=args.get("effort"),
            score=args.get("score"),
            status=args.get("status"),
        )
    if name == "delete_backlog_item":
        return await delete_backlog_item(store, item_id=args["id"])
    # ── PO Artifacts ───────────────────────────────────────────────────────── #
    if name == "save_po_artifact":
        return await save_po_artifact(
            store,
            kind=args["kind"],
            target=args["target"],
            content=args.get("content"),
            meta=args.get("meta"),
        )
    if name == "list_po_artifacts":
        return await list_po_artifacts(
            store, kind=args.get("kind"), target=args.get("target"), limit=args.get("limit", 50)
        )
    if name == "get_po_artifact":
        return await get_po_artifact(store, artifact_id=args["id"])
    if name == "delete_po_artifact":
        return await delete_po_artifact(store, artifact_id=args["id"])
    raise KeyError(name)


# ── Tenant plumbing (credencial-zero) ─────────────────────────────────────────
# Bootstrap de schema roda UMA vez por tenant/processo (idempotente de qualquer forma).
_SCHEMA_READY: set[str] = set()
_SCHEMA_LOCK = asyncio.Lock()


async def _ensure_tenant_schema(settings: ProductOwnerSettings, tenant_id: str) -> None:
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
    name: str, arguments: dict[str, Any], settings: ProductOwnerSettings, tenant_id: str
) -> dict[str, Any]:
    """Abre a sessão tenant-scoped (credencial-zero), garante o schema e despacha."""
    await _ensure_tenant_schema(settings, tenant_id)
    async with for_tenant(tenant_id) as session:
        store = ProductOwnerStore(session)
        return await _dispatch(name, arguments, store)


# ── HTTP Sidecar ──────────────────────────────────────────────────────────────


def _build_http_app(settings: ProductOwnerSettings) -> FastAPI:
    """Cria o sidecar HTTP (health + bridge governado /mcp/tools/*).

    Stateless quanto a store: cada chamada abre uma sessão tenant-scoped
    (credencial-zero) a partir do tenant nos claims do inner token."""
    app = FastAPI(
        title="product-owner-mcp API",
        version="0.1.0",
        docs_url="/docs" if settings.docs_enabled else None,  # false em todo ambiente
        redoc_url=None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
    )

    @app.get("/v1/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "service": "product-owner-mcp", "tools": len(_TOOL_SCHEMAS)}

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

        # Toda tool do product-owner toca estado do tenant → inner token obrigatório (não há
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


def build_server() -> tuple[Any, ProductOwnerSettings, FastAPI]:
    """Inicializa o MCP Server (stdio), settings e o sidecar HTTP.

    A persistência é tenant-scoped e resolvida por-request (credencial-zero).
    ``orm.configure(settings)`` registra a fonte admin (ADMIN_DB_*) usada para
    resolver o tenant → credencial do seu banco via PLATFORMS."""
    settings = get_settings()
    settings.enforce_security_invariants()  # fail-fast STD-SEC-001/004/006
    configure_logging(settings)  # logging estruturado JSON (STD-OBS-001)
    configure(settings)  # bootstrap credencial-zero (ORM-H-12): admin source p/ for_tenant
    http_app = _build_http_app(settings)
    _log.info("product_owner_mcp_ready tools=%d engine=%s", len(_TOOL_SCHEMAS), settings.DB_ENGINE)

    server: Server = Server("product-owner-mcp-server")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(name=name, description=meta["description"], inputSchema=meta["schema"])
            for name, meta in _TOOL_SCHEMAS.items()
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any] | None) -> list[TextContent]:
        # O transporte stdio não carrega o inner token (logo, sem tenant). product-owner-mcp
        # é gateway-only: a execução real entra pelo sidecar HTTP (/mcp/tools/call), onde
        # o tenant vem dos claims verificados. Aqui recusamos fail-closed (sem tenant).
        if name not in _TOOL_SCHEMAS:
            payload: dict[str, Any] = {"error": "unknown_tool", "tool": name}
        else:
            payload = {
                "error": "tenant_context_required",
                "tool": name,
                "detail": (
                    "product-owner-mcp é tenant-scoped e gateway-only; chame via o sidecar HTTP "
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
