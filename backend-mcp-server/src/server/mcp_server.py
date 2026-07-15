"""Servidor MCP do backend — sidecar kind=mcp_http, GATEWAY-READY (Model C).

Implementa o contrato de integração com o MCP Gateway central (platform-mcp-gateway):
  - docs/standards/STD-MCP-001-mcp-gateway-integration-contract.md  (CI-1..CI-11)
  - docs/standards/STD-SEC-006-token-model-c-inner-token.md          (inner token / audiência)

Pontos gateway-ready:
  1. /mcp/tools/list emite, por tool, inputSchema type=object + capability +
     required_scope + resource_type + data_domain (o gateway NÃO deriva por nome).
  2. /mcp/tools/call re-verifica o **inner Twin Token** (aud=mcp:backend-mcp) via
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

NOTA: backend-mcp é stateful — "o agente gera o conteúdo, a tool persiste": as tools
persistem contratos de API/schemas de banco/políticas de auth/artefatos de código/
reviews num MySQL via `BackendStore` (tenant-scoped, dual-db, credencial-zero). Não há
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
from ..config.settings import BackendSettings, get_settings
from ..db.schema import ensure_schema
from ..db.store import BackendStore
from ..tools import (
    delete_api_contract,
    delete_artifact,
    delete_auth_policy,
    delete_code_review,
    delete_database_schema,
    get_api_contract,
    get_artifact,
    get_auth_policy,
    get_code_review,
    get_database_schema,
    list_api_contracts,
    list_artifacts,
    list_auth_policies,
    list_code_reviews,
    list_database_schemas,
    save_api_contract,
    save_artifact,
    save_auth_policy,
    save_code_review,
    save_database_schema,
    update_database_schema,
)

_log = logging.getLogger(__name__)

# ── Tool Schemas + Policy metadata (STD-MCP-001 CI-2) ─────────────────────────
# Cada tool declara description/schema + os 4 campos de política:
#   capability     — id estável <namespace>.<tool> (não derivar por nome no gateway)
#   required_scope — escopo <namespace>:<resource_type>:<acao> (least-privilege)
#   resource_type  — tipo de recurso tocado
#   data_domain    — domínio de dado (governa HITL floor / classificação LGPD)
# inputSchema MUST ser type=object com properties. Consultas (list/get) usam :read;
# mutações (save/update/delete) usam :write.
# ─────────────────────────────────────────────────────────────────────────────
_STR = {"type": "string"}
_INT = {"type": "integer"}
_NUM = {"type": "number"}
_OBJ = {"type": "object"}
_ARR = {"type": "array"}
_STR_ARR = {"type": "array", "items": {"type": "string"}}


def _schema(props: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    s: dict[str, Any] = {"type": "object", "additionalProperties": False, "properties": props}
    if required:
        s["required"] = required
    return s


def _meta(cap: str, scope: str, rtype: str, domain: str, desc: str, schema: dict[str, Any]) -> dict[str, Any]:
    return {
        "description": desc,
        "capability": f"backend-mcp.{cap}",
        "required_scope": f"backend-mcp:{scope}",
        "resource_type": rtype,
        "data_domain": domain,
        "schema": schema,
    }


_TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    # ── API Contracts (upsert por endpoint+method) ─────────────────────────── #
    "save_api_contract": _meta(
        "save_api_contract",
        "api_contract:write",
        "api_contract",
        "backend",
        "Persiste (upsert) um contrato de API fornecido pelo agente (chave: endpoint+method).",
        _schema(
            {
                "endpoint": dict(_STR, description="Path do endpoint (chave natural)."),
                "method": dict(_STR, description="Método HTTP (chave natural; GET/POST/...)."),
                "description": dict(_STR, description="Descrição do endpoint (opcional)."),
                "request_schema": dict(_OBJ, description="Schema da request (opcional)."),
                "response_schema": dict(_OBJ, description="Schema da response (opcional)."),
                "status_codes": dict(_ARR, description="Status codes suportados (opcional)."),
                "status": dict(_STR, description="Status do contrato (opcional)."),
            },
            required=["endpoint", "method"],
        ),
    ),
    "list_api_contracts": _meta(
        "list_api_contracts",
        "api_contract:read",
        "api_contract",
        "backend",
        "Lista contratos de API persistidos, com filtros opcionais.",
        _schema(
            {
                "endpoint": dict(_STR, description="Filtrar por endpoint (opcional)."),
                "method": dict(_STR, description="Filtrar por método (opcional)."),
                "status": dict(_STR, description="Filtrar por status (opcional)."),
            }
        ),
    ),
    "get_api_contract": _meta(
        "get_api_contract",
        "api_contract:read",
        "api_contract",
        "backend",
        "Retorna um contrato de API por endpoint+method.",
        _schema(
            {
                "endpoint": dict(_STR, description="Path do endpoint."),
                "method": dict(_STR, description="Método HTTP."),
            },
            required=["endpoint", "method"],
        ),
    ),
    "delete_api_contract": _meta(
        "delete_api_contract",
        "api_contract:write",
        "api_contract",
        "backend",
        "Soft-delete de um contrato de API por endpoint+method.",
        _schema(
            {
                "endpoint": dict(_STR, description="Path do endpoint."),
                "method": dict(_STR, description="Método HTTP."),
            },
            required=["endpoint", "method"],
        ),
    ),
    # ── Database Schemas (histórico) ───────────────────────────────────────── #
    "save_database_schema": _meta(
        "save_database_schema",
        "database_schema:write",
        "database_schema",
        "backend",
        "Persiste um schema de banco fornecido pelo agente (atributos/relacionamentos/índices).",
        _schema(
            {
                "entity": dict(_STR, description="Entidade/tabela alvo."),
                "database_name": dict(_STR, description="Engine (postgres/mysql/...)."),
                "attributes": dict(_ARR, description="Atributos {name,type,...} (opcional)."),
                "relationships": dict(_ARR, description="Relacionamentos (opcional)."),
                "indexes": dict(_ARR, description="Índices (opcional)."),
                "constraints": dict(_ARR, description="Constraints (opcional)."),
                "status": dict(_STR, description="Status (opcional)."),
            },
            required=["entity", "database_name"],
        ),
    ),
    "list_database_schemas": _meta(
        "list_database_schemas",
        "database_schema:read",
        "database_schema",
        "backend",
        "Lista schemas de banco persistidos, com filtros opcionais.",
        _schema(
            {
                "entity": dict(_STR, description="Filtrar por entidade (opcional)."),
                "database_name": dict(_STR, description="Filtrar por engine (opcional)."),
                "status": dict(_STR, description="Filtrar por status (opcional)."),
            }
        ),
    ),
    "get_database_schema": _meta(
        "get_database_schema",
        "database_schema:read",
        "database_schema",
        "backend",
        "Retorna um schema de banco por id.",
        _schema({"id": dict(_INT, description="Id do schema.")}, required=["id"]),
    ),
    "update_database_schema": _meta(
        "update_database_schema",
        "database_schema:write",
        "database_schema",
        "backend",
        "Atualiza campos mutáveis de um schema de banco.",
        _schema(
            {
                "id": dict(_INT, description="Id do schema."),
                "database_name": dict(_STR, description="Novo engine (opcional)."),
                "attributes": dict(_ARR, description="Novos atributos (opcional)."),
                "relationships": dict(_ARR, description="Novos relacionamentos (opcional)."),
                "indexes": dict(_ARR, description="Novos índices (opcional)."),
                "constraints": dict(_ARR, description="Novas constraints (opcional)."),
                "status": dict(_STR, description="Novo status (opcional)."),
            },
            required=["id"],
        ),
    ),
    "delete_database_schema": _meta(
        "delete_database_schema",
        "database_schema:write",
        "database_schema",
        "backend",
        "Soft-delete de um schema de banco por id.",
        _schema({"id": dict(_INT, description="Id do schema.")}, required=["id"]),
    ),
    # ── Auth Policies (upsert por resource) ────────────────────────────────── #
    "save_auth_policy": _meta(
        "save_auth_policy",
        "auth_policy:write",
        "auth_policy",
        "security",
        "Persiste (upsert) a política de auth de um recurso com os campos fornecidos.",
        _schema(
            {
                "resource": dict(_STR, description="Recurso protegido (chave natural única)."),
                "auth_type": dict(_STR, description="Tipo de auth (jwt/oauth/...)."),
                "roles": dict(_STR_ARR, description="Papéis autorizados (opcional)."),
                "data_sensitivity": dict(_STR, description="Sensibilidade do dado (opcional)."),
                "rules": dict(_OBJ, description="Regras adicionais (opcional)."),
                "status": dict(_STR, description="Status da política (opcional)."),
            },
            required=["resource", "auth_type"],
        ),
    ),
    "list_auth_policies": _meta(
        "list_auth_policies",
        "auth_policy:read",
        "auth_policy",
        "security",
        "Lista políticas de auth persistidas, com filtros opcionais.",
        _schema(
            {
                "auth_type": dict(_STR, description="Filtrar por tipo de auth (opcional)."),
                "status": dict(_STR, description="Filtrar por status (opcional)."),
            }
        ),
    ),
    "get_auth_policy": _meta(
        "get_auth_policy",
        "auth_policy:read",
        "auth_policy",
        "security",
        "Retorna a política de auth de um recurso.",
        _schema({"resource": dict(_STR, description="Recurso alvo.")}, required=["resource"]),
    ),
    "delete_auth_policy": _meta(
        "delete_auth_policy",
        "auth_policy:write",
        "auth_policy",
        "security",
        "Soft-delete da política de auth de um recurso.",
        _schema({"resource": dict(_STR, description="Recurso alvo.")}, required=["resource"]),
    ),
    # ── Backend Artifacts (histórico append-only) ──────────────────────────── #
    "save_artifact": _meta(
        "save_artifact",
        "artifact:write",
        "artifact",
        "backend",
        "Persiste um artefato de código backend (router/migration/service/...) gerado pelo agente.",
        _schema(
            {
                "kind": dict(
                    _STR,
                    description=(
                        "Tipo: router|migration|service_layer|repository|openapi_spec|"
                        "nestjs_controller|integration."
                    ),
                ),
                "target": dict(_STR, description="Alvo (nome/módulo/serviço)."),
                "content": dict(_STR, description="Código gerado pelo agente."),
                "language": dict(_STR, description="Linguagem (python/typescript/...; opcional)."),
                "framework": dict(_STR, description="Framework (fastapi/nestjs/...; opcional)."),
                "meta": dict(_OBJ, description="Metadados adicionais (opcional)."),
            },
            required=["kind", "target", "content"],
        ),
    ),
    "list_artifacts": _meta(
        "list_artifacts",
        "artifact:read",
        "artifact",
        "backend",
        "Lista artefatos de código persistidos, com filtros opcionais.",
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
        "backend",
        "Retorna um artefato de código por id.",
        _schema({"id": dict(_INT, description="Id do artefato.")}, required=["id"]),
    ),
    "delete_artifact": _meta(
        "delete_artifact",
        "artifact:write",
        "artifact",
        "backend",
        "Soft-delete de um artefato de código por id.",
        _schema({"id": dict(_INT, description="Id do artefato.")}, required=["id"]),
    ),
    # ── Code Reviews (histórico append-only) ───────────────────────────────── #
    "save_code_review": _meta(
        "save_code_review",
        "code_review:write",
        "code_review",
        "backend",
        "Persiste uma revisão de código backend (achados/scores) fornecida pelo agente.",
        _schema(
            {
                "target": dict(_STR, description="Arquivo/módulo/serviço revisado."),
                "language": dict(_STR, description="Linguagem (python/typescript/...)."),
                "focus": dict(_STR_ARR, description="Focos da revisão (opcional)."),
                "findings": dict(_ARR, description="Achados da revisão (opcional)."),
                "security_score": dict(_NUM, description="Score de segurança (opcional)."),
                "performance_score": dict(_NUM, description="Score de performance (opcional)."),
                "summary": dict(_STR, description="Resumo da revisão (opcional)."),
                "status": dict(_STR, description="Status (opcional)."),
            },
            required=["target", "language"],
        ),
    ),
    "list_code_reviews": _meta(
        "list_code_reviews",
        "code_review:read",
        "code_review",
        "backend",
        "Lista revisões de código persistidas, com filtros opcionais.",
        _schema(
            {
                "target": dict(_STR, description="Filtrar por alvo (opcional)."),
                "language": dict(_STR, description="Filtrar por linguagem (opcional)."),
                "status": dict(_STR, description="Filtrar por status (opcional)."),
            }
        ),
    ),
    "get_code_review": _meta(
        "get_code_review",
        "code_review:read",
        "code_review",
        "backend",
        "Retorna uma revisão de código por id.",
        _schema({"id": dict(_INT, description="Id da revisão.")}, required=["id"]),
    ),
    "delete_code_review": _meta(
        "delete_code_review",
        "code_review:write",
        "code_review",
        "backend",
        "Soft-delete de uma revisão de código por id.",
        _schema({"id": dict(_INT, description="Id da revisão.")}, required=["id"]),
    ),
}

# backend-mcp não expõe tool tokenless: TODAS as tools tocam estado do tenant e
# exigem inner token válido (fail-closed). O liveness fica no /v1/health (sem tool).
_EXEMPT_TOOLS: frozenset[str] = frozenset()
# Denylist fail-safe: tools que retornam segredos NUNCA saem pelo gateway (CI-7).
_EXCLUDE_TOOLS: frozenset[str] = frozenset()

# Campos de policy repassados no /mcp/tools/list (o gateway lê estes campos).
_POLICY_FIELDS = ("capability", "required_scope", "resource_type", "data_domain")


# ── Verificação do inner Twin Token (STD-SEC-006 / CI-4/CI-5) ─────────────────


def _verify_inner_token(twin_token: str, settings: BackendSettings) -> dict[str, Any]:
    """Re-verifica o inner Twin Token na PRÓPRIA audiência (mcp:backend-mcp).

    O gateway já verificou o front token; o backend é 'one more verified client'
    (defense in depth). RS256 via JWKS do platform-admin; audiência exata; jti
    obrigatório. Levanta em qualquer falha (fail-closed).
    """
    if not settings.mcp_twin_audience or not settings.url_admin_twin_jwks:
        raise PermissionError(
            "integração com o gateway não configurada: defina MCP_TWIN_AUDIENCE "
            "(mcp:backend-mcp) e URL_ADMIN_TWIN_JWKS (ver STD-SEC-006 / IT-006)."
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


async def _dispatch(name: str, args: dict[str, Any], store: BackendStore) -> dict[str, Any]:
    """Despacha a chamada para a tool (async). O tenant NÃO viaja nos args (INV-3):
    o ``store`` já está ligado ao pool do tenant (resolvido dos claims do inner token)."""
    # ── API Contracts ──────────────────────────────────────────────────────── #
    if name == "save_api_contract":
        return await save_api_contract(
            store,
            endpoint=args["endpoint"],
            method=args["method"],
            description=args.get("description"),
            request_schema=args.get("request_schema"),
            response_schema=args.get("response_schema"),
            status_codes=args.get("status_codes"),
            status=args.get("status"),
        )
    if name == "list_api_contracts":
        return await list_api_contracts(
            store,
            endpoint=args.get("endpoint"),
            method=args.get("method"),
            status=args.get("status"),
        )
    if name == "get_api_contract":
        return await get_api_contract(store, endpoint=args["endpoint"], method=args["method"])
    if name == "delete_api_contract":
        return await delete_api_contract(store, endpoint=args["endpoint"], method=args["method"])
    # ── Database Schemas ───────────────────────────────────────────────────── #
    if name == "save_database_schema":
        return await save_database_schema(
            store,
            entity=args["entity"],
            database_name=args["database_name"],
            attributes=args.get("attributes"),
            relationships=args.get("relationships"),
            indexes=args.get("indexes"),
            constraints=args.get("constraints"),
            status=args.get("status"),
        )
    if name == "list_database_schemas":
        return await list_database_schemas(
            store,
            entity=args.get("entity"),
            database_name=args.get("database_name"),
            status=args.get("status"),
        )
    if name == "get_database_schema":
        return await get_database_schema(store, schema_id=args["id"])
    if name == "update_database_schema":
        return await update_database_schema(
            store,
            schema_id=args["id"],
            database_name=args.get("database_name"),
            attributes=args.get("attributes"),
            relationships=args.get("relationships"),
            indexes=args.get("indexes"),
            constraints=args.get("constraints"),
            status=args.get("status"),
        )
    if name == "delete_database_schema":
        return await delete_database_schema(store, schema_id=args["id"])
    # ── Auth Policies ──────────────────────────────────────────────────────── #
    if name == "save_auth_policy":
        return await save_auth_policy(
            store,
            resource=args["resource"],
            auth_type=args["auth_type"],
            roles=args.get("roles"),
            data_sensitivity=args.get("data_sensitivity"),
            rules=args.get("rules"),
            status=args.get("status"),
        )
    if name == "list_auth_policies":
        return await list_auth_policies(store, auth_type=args.get("auth_type"), status=args.get("status"))
    if name == "get_auth_policy":
        return await get_auth_policy(store, resource=args["resource"])
    if name == "delete_auth_policy":
        return await delete_auth_policy(store, resource=args["resource"])
    # ── Backend Artifacts ──────────────────────────────────────────────────── #
    if name == "save_artifact":
        return await save_artifact(
            store,
            kind=args["kind"],
            target=args["target"],
            content=args["content"],
            language=args.get("language"),
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
    # ── Code Reviews ───────────────────────────────────────────────────────── #
    if name == "save_code_review":
        return await save_code_review(
            store,
            target=args["target"],
            language=args["language"],
            focus=args.get("focus"),
            findings=args.get("findings"),
            security_score=args.get("security_score"),
            performance_score=args.get("performance_score"),
            summary=args.get("summary"),
            status=args.get("status"),
        )
    if name == "list_code_reviews":
        return await list_code_reviews(
            store, target=args.get("target"), language=args.get("language"), status=args.get("status")
        )
    if name == "get_code_review":
        return await get_code_review(store, review_id=args["id"])
    if name == "delete_code_review":
        return await delete_code_review(store, review_id=args["id"])
    raise KeyError(name)


# ── Tenant plumbing (credencial-zero) ─────────────────────────────────────────
# Bootstrap de schema roda UMA vez por tenant/processo (idempotente de qualquer forma).
_SCHEMA_READY: set[str] = set()
_SCHEMA_LOCK = asyncio.Lock()


async def _ensure_tenant_schema(settings: BackendSettings, tenant_id: str) -> None:
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
    name: str, arguments: dict[str, Any], settings: BackendSettings, tenant_id: str
) -> dict[str, Any]:
    """Abre a sessão tenant-scoped (credencial-zero), garante o schema e despacha."""
    await _ensure_tenant_schema(settings, tenant_id)
    async with for_tenant(tenant_id) as session:
        store = BackendStore(session)
        return await _dispatch(name, arguments, store)


# ── HTTP Sidecar ──────────────────────────────────────────────────────────────


def _build_http_app(settings: BackendSettings) -> FastAPI:
    """Cria o sidecar HTTP (health + bridge governado /mcp/tools/*).

    Stateless quanto a store: cada chamada abre uma sessão tenant-scoped
    (credencial-zero) a partir do tenant nos claims do inner token."""
    app = FastAPI(
        title="backend-mcp API",
        version="0.1.0",
        docs_url="/docs" if settings.docs_enabled else None,  # false em todo ambiente
        redoc_url=None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
    )

    @app.get("/v1/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "service": "backend-mcp", "tools": len(_TOOL_SCHEMAS)}

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

        # Toda tool do backend toca estado do tenant → inner token obrigatório (não há
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


def build_server() -> tuple[Any, BackendSettings, FastAPI]:
    """Inicializa o MCP Server (stdio), settings e o sidecar HTTP.

    A persistência é tenant-scoped e resolvida por-request (credencial-zero).
    ``orm.configure(settings)`` registra a fonte admin (ADMIN_DB_*) usada para
    resolver o tenant → credencial do seu banco via PLATFORMS."""
    settings = get_settings()
    settings.enforce_security_invariants()  # fail-fast STD-SEC-001/004/006
    configure_logging(settings)  # logging estruturado JSON (STD-OBS-001)
    configure(settings)  # bootstrap credencial-zero (ORM-H-12): admin source p/ for_tenant
    http_app = _build_http_app(settings)
    _log.info("backend_mcp_ready tools=%d engine=%s", len(_TOOL_SCHEMAS), settings.DB_ENGINE)

    server: Server = Server("backend-mcp-server")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(name=name, description=meta["description"], inputSchema=meta["schema"])
            for name, meta in _TOOL_SCHEMAS.items()
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any] | None) -> list[TextContent]:
        # O transporte stdio não carrega o inner token (logo, sem tenant). backend-mcp
        # é gateway-only: a execução real entra pelo sidecar HTTP (/mcp/tools/call), onde
        # o tenant vem dos claims verificados. Aqui recusamos fail-closed (sem tenant).
        if name not in _TOOL_SCHEMAS:
            payload: dict[str, Any] = {"error": "unknown_tool", "tool": name}
        else:
            payload = {
                "error": "tenant_context_required",
                "tool": name,
                "detail": (
                    "backend-mcp é tenant-scoped e gateway-only; chame via o sidecar HTTP "
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
