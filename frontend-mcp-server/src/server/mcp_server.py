"""Servidor MCP do frontend — sidecar kind=mcp_http, GATEWAY-READY (Model C).

Implementa o contrato de integração com o MCP Gateway central (platform-mcp-gateway):
  - docs/standards/STD-MCP-001-mcp-gateway-integration-contract.md  (CI-1..CI-11)
  - docs/standards/STD-SEC-006-token-model-c-inner-token.md          (inner token / audiência)

Pontos gateway-ready:
  1. /mcp/tools/list emite, por tool, inputSchema type=object + capability +
     required_scope + resource_type + data_domain (o gateway NÃO deriva por nome).
  2. /mcp/tools/call re-verifica o **inner Twin Token** (aud=mcp:frontend-mcp) via
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

NOTA: frontend-mcp é stateful — "o agente gera o conteúdo, a tool persiste": as
tools persistem componentes/páginas/formulários/stories/artefatos num MySQL via
`FrontendStore` (tenant-scoped, dual-db, credencial-zero). Não há backend REST
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
from ..config.settings import FrontendSettings, get_settings
from ..db.schema import ensure_schema
from ..db.store import FrontendStore
from ..tools import (
    delete_artifact,
    delete_component,
    delete_form,
    delete_page,
    delete_story,
    get_artifact,
    get_component,
    get_form,
    get_page,
    get_story,
    list_artifacts,
    list_components,
    list_forms,
    list_pages,
    list_stories,
    save_artifact,
    save_component,
    save_form,
    save_story,
    set_page,
    update_component,
    update_form,
    update_story,
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
        "capability": f"frontend-mcp.{cap}",
        "required_scope": f"frontend-mcp:{scope}",
        "resource_type": rtype,
        "data_domain": domain,
        "schema": schema,
    }


_TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    # ── Components ─────────────────────────────────────────────────────────── #
    "save_component": _meta(
        "save_component",
        "component:write",
        "component",
        "frontend",
        "Persiste um componente React fornecido pelo agente (o código vem do agente).",
        _schema(
            {
                "name": dict(_STR, description="Nome do componente."),
                "variant": dict(_STR, description="Variante (functional/class; default functional)."),
                "framework": dict(_STR, description="Framework (react/preact; opcional)."),
                "styling": dict(_STR, description="Estratégia de estilo (tailwind/css-modules; opcional)."),
                "props": dict(_OBJ, description="Props/interface do componente (opcional)."),
                "code": dict(_STR, description="Código-fonte gerado pelo agente (opcional)."),
                "status": dict(_STR, description="Status (opcional)."),
            },
            required=["name"],
        ),
    ),
    "list_components": _meta(
        "list_components",
        "component:read",
        "component",
        "frontend",
        "Lista componentes persistidos, com filtros opcionais.",
        _schema(
            {
                "name": dict(_STR, description="Filtrar por nome (opcional)."),
                "framework": dict(_STR, description="Filtrar por framework (opcional)."),
                "status": dict(_STR, description="Filtrar por status (opcional)."),
            }
        ),
    ),
    "get_component": _meta(
        "get_component",
        "component:read",
        "component",
        "frontend",
        "Retorna um componente por id.",
        _schema({"id": dict(_INT, description="Id do componente.")}, required=["id"]),
    ),
    "update_component": _meta(
        "update_component",
        "component:write",
        "component",
        "frontend",
        "Atualiza campos mutáveis de um componente (variant/framework/styling/props/code/status).",
        _schema(
            {
                "id": dict(_INT, description="Id do componente."),
                "variant": dict(_STR, description="Nova variante (opcional)."),
                "framework": dict(_STR, description="Novo framework (opcional)."),
                "styling": dict(_STR, description="Nova estratégia de estilo (opcional)."),
                "props": dict(_OBJ, description="Novos props (opcional)."),
                "code": dict(_STR, description="Novo código-fonte (opcional)."),
                "status": dict(_STR, description="Novo status (opcional)."),
            },
            required=["id"],
        ),
    ),
    "delete_component": _meta(
        "delete_component",
        "component:write",
        "component",
        "frontend",
        "Soft-delete de um componente por id.",
        _schema({"id": dict(_INT, description="Id do componente.")}, required=["id"]),
    ),
    # ── Pages (upsert por route) ───────────────────────────────────────────── #
    "set_page": _meta(
        "set_page",
        "page:write",
        "page",
        "frontend",
        "Define (upsert) a página de uma rota com o código fornecido pelo agente.",
        _schema(
            {
                "route": dict(_STR, description="Rota da página (chave natural única)."),
                "title": dict(_STR, description="Título da página (opcional)."),
                "framework": dict(_STR, description="Framework (nextjs/remix; opcional)."),
                "page_type": dict(_STR, description="Tipo (app-route/pages-route; opcional)."),
                "code": dict(_STR, description="Código-fonte da página (opcional)."),
                "meta": dict(_OBJ, description="Metadados (layout/metadata/loaders; opcional)."),
                "status": dict(_STR, description="Status (opcional)."),
            },
            required=["route"],
        ),
    ),
    "list_pages": _meta(
        "list_pages",
        "page:read",
        "page",
        "frontend",
        "Lista páginas persistidas, com filtros opcionais.",
        _schema(
            {
                "framework": dict(_STR, description="Filtrar por framework (opcional)."),
                "status": dict(_STR, description="Filtrar por status (opcional)."),
            }
        ),
    ),
    "get_page": _meta(
        "get_page",
        "page:read",
        "page",
        "frontend",
        "Retorna a página de uma rota.",
        _schema({"route": dict(_STR, description="Rota da página.")}, required=["route"]),
    ),
    "delete_page": _meta(
        "delete_page",
        "page:write",
        "page",
        "frontend",
        "Soft-delete da página de uma rota.",
        _schema({"route": dict(_STR, description="Rota da página.")}, required=["route"]),
    ),
    # ── Forms ──────────────────────────────────────────────────────────────── #
    "save_form": _meta(
        "save_form",
        "form:write",
        "form",
        "frontend",
        "Persiste um formulário fornecido pelo agente (campos/código vêm do agente).",
        _schema(
            {
                "name": dict(_STR, description="Nome do formulário."),
                "library": dict(_STR, description="Biblioteca (react-hook-form/formik; opcional)."),
                "validation": dict(_STR, description="Validação (zod/yup; opcional)."),
                "fields": dict(_ARR, description="Campos + regras (opcional)."),
                "code": dict(_STR, description="Código-fonte gerado (opcional)."),
                "status": dict(_STR, description="Status (opcional)."),
            },
            required=["name"],
        ),
    ),
    "list_forms": _meta(
        "list_forms",
        "form:read",
        "form",
        "frontend",
        "Lista formulários persistidos, com filtros opcionais.",
        _schema(
            {
                "name": dict(_STR, description="Filtrar por nome (opcional)."),
                "status": dict(_STR, description="Filtrar por status (opcional)."),
            }
        ),
    ),
    "get_form": _meta(
        "get_form",
        "form:read",
        "form",
        "frontend",
        "Retorna um formulário por id.",
        _schema({"id": dict(_INT, description="Id do formulário.")}, required=["id"]),
    ),
    "update_form": _meta(
        "update_form",
        "form:write",
        "form",
        "frontend",
        "Atualiza campos mutáveis de um formulário.",
        _schema(
            {
                "id": dict(_INT, description="Id do formulário."),
                "library": dict(_STR, description="Nova biblioteca (opcional)."),
                "validation": dict(_STR, description="Nova validação (opcional)."),
                "fields": dict(_ARR, description="Novos campos (opcional)."),
                "code": dict(_STR, description="Novo código-fonte (opcional)."),
                "status": dict(_STR, description="Novo status (opcional)."),
            },
            required=["id"],
        ),
    ),
    "delete_form": _meta(
        "delete_form",
        "form:write",
        "form",
        "frontend",
        "Soft-delete de um formulário por id.",
        _schema({"id": dict(_INT, description="Id do formulário.")}, required=["id"]),
    ),
    # ── Stories ────────────────────────────────────────────────────────────── #
    "save_story": _meta(
        "save_story",
        "story:write",
        "story",
        "frontend",
        "Persiste uma story de Storybook fornecida pelo agente (código/estados vêm do agente).",
        _schema(
            {
                "component": dict(_STR, description="Componente-alvo da story."),
                "title": dict(_STR, description="Título da story (opcional)."),
                "framework": dict(_STR, description="Framework (storybook/csf; opcional)."),
                "stories": dict(_ARR, description="Lista de estados/stories (opcional)."),
                "code": dict(_STR, description="Código-fonte gerado (opcional)."),
                "status": dict(_STR, description="Status (opcional)."),
            },
            required=["component"],
        ),
    ),
    "list_stories": _meta(
        "list_stories",
        "story:read",
        "story",
        "frontend",
        "Lista stories persistidas, com filtros opcionais.",
        _schema(
            {
                "component": dict(_STR, description="Filtrar por componente (opcional)."),
                "status": dict(_STR, description="Filtrar por status (opcional)."),
            }
        ),
    ),
    "get_story": _meta(
        "get_story",
        "story:read",
        "story",
        "frontend",
        "Retorna uma story por id.",
        _schema({"id": dict(_INT, description="Id da story.")}, required=["id"]),
    ),
    "update_story": _meta(
        "update_story",
        "story:write",
        "story",
        "frontend",
        "Atualiza campos mutáveis de uma story.",
        _schema(
            {
                "id": dict(_INT, description="Id da story."),
                "title": dict(_STR, description="Novo título (opcional)."),
                "framework": dict(_STR, description="Novo framework (opcional)."),
                "stories": dict(_ARR, description="Novos estados/stories (opcional)."),
                "code": dict(_STR, description="Novo código-fonte (opcional)."),
                "status": dict(_STR, description="Novo status (opcional)."),
            },
            required=["id"],
        ),
    ),
    "delete_story": _meta(
        "delete_story",
        "story:write",
        "story",
        "frontend",
        "Soft-delete de uma story por id.",
        _schema({"id": dict(_INT, description="Id da story.")}, required=["id"]),
    ),
    # ── Artifacts (histórico append-only) ──────────────────────────────────── #
    "save_artifact": _meta(
        "save_artifact",
        "artifact:write",
        "artifact",
        "frontend",
        "Persiste um artefato de UI (código/scaffold) gerado pelo agente.",
        _schema(
            {
                "kind": dict(
                    _STR,
                    description=(
                        "Tipo: react_component|nextjs_page|form|storybook_story|hook|"
                        "layout|context|style|util|api_client."
                    ),
                ),
                "target": dict(_STR, description="Alvo (componente/rota/módulo)."),
                "content": dict(_STR, description="Código/scaffold gerado pelo agente."),
                "framework": dict(_STR, description="Framework (opcional)."),
                "meta": dict(_OBJ, description="Metadados adicionais (opcional)."),
            },
            required=["kind", "target", "content"],
        ),
    ),
    "list_artifacts": _meta(
        "list_artifacts",
        "artifact:read",
        "artifact",
        "frontend",
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
        "frontend",
        "Retorna um artefato por id.",
        _schema({"id": dict(_INT, description="Id do artefato.")}, required=["id"]),
    ),
    "delete_artifact": _meta(
        "delete_artifact",
        "artifact:write",
        "artifact",
        "frontend",
        "Soft-delete de um artefato por id.",
        _schema({"id": dict(_INT, description="Id do artefato.")}, required=["id"]),
    ),
}

# frontend-mcp não expõe tool tokenless: TODAS as tools tocam estado do tenant e
# exigem inner token válido (fail-closed). O liveness fica no /v1/health (sem tool).
_EXEMPT_TOOLS: frozenset[str] = frozenset()
# Denylist fail-safe: tools que retornam segredos NUNCA saem pelo gateway (CI-7).
_EXCLUDE_TOOLS: frozenset[str] = frozenset()

# Campos de policy repassados no /mcp/tools/list (o gateway lê estes campos).
_POLICY_FIELDS = ("capability", "required_scope", "resource_type", "data_domain")


# ── Verificação do inner Twin Token (STD-SEC-006 / CI-4/CI-5) ─────────────────


def _verify_inner_token(twin_token: str, settings: FrontendSettings) -> dict[str, Any]:
    """Re-verifica o inner Twin Token na PRÓPRIA audiência (mcp:frontend-mcp).

    O gateway já verificou o front token; o backend é 'one more verified client'
    (defense in depth). RS256 via JWKS do platform-admin; audiência exata; jti
    obrigatório. Levanta em qualquer falha (fail-closed).
    """
    if not settings.mcp_twin_audience or not settings.url_admin_twin_jwks:
        raise PermissionError(
            "integração com o gateway não configurada: defina MCP_TWIN_AUDIENCE "
            "(mcp:frontend-mcp) e URL_ADMIN_TWIN_JWKS (ver STD-SEC-006 / IT-006)."
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


async def _dispatch(name: str, args: dict[str, Any], store: FrontendStore) -> dict[str, Any]:
    """Despacha a chamada para a tool (async). O tenant NÃO viaja nos args (INV-3):
    o ``store`` já está ligado ao pool do tenant (resolvido dos claims do inner token)."""
    # ── Components ─────────────────────────────────────────────────────────── #
    if name == "save_component":
        return await save_component(
            store,
            name=args["name"],
            variant=args.get("variant", "functional"),
            framework=args.get("framework"),
            styling=args.get("styling"),
            props=args.get("props"),
            code=args.get("code"),
            status=args.get("status"),
        )
    if name == "list_components":
        return await list_components(
            store,
            name=args.get("name"),
            framework=args.get("framework"),
            status=args.get("status"),
        )
    if name == "get_component":
        return await get_component(store, component_id=args["id"])
    if name == "update_component":
        return await update_component(
            store,
            component_id=args["id"],
            variant=args.get("variant"),
            framework=args.get("framework"),
            styling=args.get("styling"),
            props=args.get("props"),
            code=args.get("code"),
            status=args.get("status"),
        )
    if name == "delete_component":
        return await delete_component(store, component_id=args["id"])
    # ── Pages (upsert por route) ───────────────────────────────────────────── #
    if name == "set_page":
        return await set_page(
            store,
            route=args["route"],
            title=args.get("title"),
            framework=args.get("framework"),
            page_type=args.get("page_type"),
            code=args.get("code"),
            meta=args.get("meta"),
            status=args.get("status"),
        )
    if name == "list_pages":
        return await list_pages(store, framework=args.get("framework"), status=args.get("status"))
    if name == "get_page":
        return await get_page(store, route=args["route"])
    if name == "delete_page":
        return await delete_page(store, route=args["route"])
    # ── Forms ──────────────────────────────────────────────────────────────── #
    if name == "save_form":
        return await save_form(
            store,
            name=args["name"],
            library=args.get("library"),
            validation=args.get("validation"),
            fields=args.get("fields"),
            code=args.get("code"),
            status=args.get("status"),
        )
    if name == "list_forms":
        return await list_forms(store, name=args.get("name"), status=args.get("status"))
    if name == "get_form":
        return await get_form(store, form_id=args["id"])
    if name == "update_form":
        return await update_form(
            store,
            form_id=args["id"],
            library=args.get("library"),
            validation=args.get("validation"),
            fields=args.get("fields"),
            code=args.get("code"),
            status=args.get("status"),
        )
    if name == "delete_form":
        return await delete_form(store, form_id=args["id"])
    # ── Stories ────────────────────────────────────────────────────────────── #
    if name == "save_story":
        return await save_story(
            store,
            component=args["component"],
            title=args.get("title"),
            framework=args.get("framework"),
            stories=args.get("stories"),
            code=args.get("code"),
            status=args.get("status"),
        )
    if name == "list_stories":
        return await list_stories(store, component=args.get("component"), status=args.get("status"))
    if name == "get_story":
        return await get_story(store, story_id=args["id"])
    if name == "update_story":
        return await update_story(
            store,
            story_id=args["id"],
            title=args.get("title"),
            framework=args.get("framework"),
            stories=args.get("stories"),
            code=args.get("code"),
            status=args.get("status"),
        )
    if name == "delete_story":
        return await delete_story(store, story_id=args["id"])
    # ── Artifacts ──────────────────────────────────────────────────────────── #
    if name == "save_artifact":
        return await save_artifact(
            store,
            kind=args["kind"],
            target=args["target"],
            content=args["content"],
            framework=args.get("framework"),
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


async def _ensure_tenant_schema(settings: FrontendSettings, tenant_id: str) -> None:
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
    name: str, arguments: dict[str, Any], settings: FrontendSettings, tenant_id: str
) -> dict[str, Any]:
    """Abre a sessão tenant-scoped (credencial-zero), garante o schema e despacha."""
    await _ensure_tenant_schema(settings, tenant_id)
    async with for_tenant(tenant_id) as session:
        store = FrontendStore(session)
        return await _dispatch(name, arguments, store)


# ── HTTP Sidecar ──────────────────────────────────────────────────────────────


def _build_http_app(settings: FrontendSettings) -> FastAPI:
    """Cria o sidecar HTTP (health + bridge governado /mcp/tools/*).

    Stateless quanto a store: cada chamada abre uma sessão tenant-scoped
    (credencial-zero) a partir do tenant nos claims do inner token."""
    app = FastAPI(
        title="frontend-mcp API",
        version="0.1.0",
        docs_url="/docs" if settings.docs_enabled else None,  # false em todo ambiente
        redoc_url=None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
    )

    @app.get("/v1/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "service": "frontend-mcp", "tools": len(_TOOL_SCHEMAS)}

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

        # Toda tool do frontend toca estado do tenant → inner token obrigatório (não há
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


def build_server() -> tuple[Any, FrontendSettings, FastAPI]:
    """Inicializa o MCP Server (stdio), settings e o sidecar HTTP.

    A persistência é tenant-scoped e resolvida por-request (credencial-zero).
    ``orm.configure(settings)`` registra a fonte admin (ADMIN_DB_*) usada para
    resolver o tenant → credencial do seu banco via PLATFORMS."""
    settings = get_settings()
    settings.enforce_security_invariants()  # fail-fast STD-SEC-001/004/006
    configure_logging(settings)  # logging estruturado JSON (STD-OBS-001)
    configure(settings)  # bootstrap credencial-zero (ORM-H-12): admin source p/ for_tenant
    http_app = _build_http_app(settings)
    _log.info("frontend_mcp_ready tools=%d engine=%s", len(_TOOL_SCHEMAS), settings.DB_ENGINE)

    server: Server = Server("frontend-mcp-server")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(name=name, description=meta["description"], inputSchema=meta["schema"])
            for name, meta in _TOOL_SCHEMAS.items()
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any] | None) -> list[TextContent]:
        # O transporte stdio não carrega o inner token (logo, sem tenant). frontend-mcp
        # é gateway-only: a execução real entra pelo sidecar HTTP (/mcp/tools/call), onde
        # o tenant vem dos claims verificados. Aqui recusamos fail-closed (sem tenant).
        if name not in _TOOL_SCHEMAS:
            payload: dict[str, Any] = {"error": "unknown_tool", "tool": name}
        else:
            payload = {
                "error": "tenant_context_required",
                "tool": name,
                "detail": (
                    "frontend-mcp é tenant-scoped e gateway-only; chame via o sidecar HTTP "
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
