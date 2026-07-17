"""Servidor MCP do devops — sidecar kind=mcp_http, GATEWAY-READY (Model C).

Implementa o contrato de integração com o MCP Gateway central (platform-mcp-gateway):
  - docs/standards/STD-MCP-001-mcp-gateway-integration-contract.md  (CI-1..CI-11)
  - docs/standards/STD-SEC-006-token-model-c-inner-token.md          (inner token / audiência)

Pontos gateway-ready:
  1. /mcp/tools/list emite, por tool, inputSchema type=object + capability +
     required_scope + resource_type + data_domain (o gateway NÃO deriva por nome).
  2. /mcp/tools/call re-verifica o **inner Twin Token** (aud=mcp:devops-mcp) via
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

NOTA: devops-mcp é stateful — "o agente gera o conteúdo, a tool persiste": as tools
persistem artefatos IaC/pipelines/deployments/environments/service configs num MySQL
via `DevopsStore` (tenant-scoped, dual-db, credencial-zero). Não há backend REST
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
from ..config.settings import DevopsSettings, get_settings
from ..db.schema import ensure_schema
from ..db.store import DevopsStore
from ..tools import (
    delete_artifact,
    delete_deployment,
    delete_environment,
    delete_pipeline,
    delete_service_config,
    get_artifact,
    get_deployment,
    get_environment,
    get_pipeline,
    get_service_config,
    list_artifacts,
    list_deployments,
    list_environments,
    list_pipelines,
    list_service_configs,
    save_artifact,
    save_deployment,
    save_pipeline,
    set_environment,
    set_service_config,
    update_deployment_status,
    update_pipeline,
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
        "capability": f"devops-mcp.{cap}",
        "required_scope": f"devops-mcp:{scope}",
        "resource_type": rtype,
        "data_domain": domain,
        "schema": schema,
    }


_TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    # ── Artifacts (histórico append-only) ──────────────────────────────────── #
    "save_artifact": _meta(
        "save_artifact",
        "artifact:write",
        "artifact",
        "devops",
        "Persiste um artefato de infra-as-code (Dockerfile/pipeline/chart/manifesto) gerado pelo agente.",
        _schema(
            {
                "kind": dict(
                    _STR,
                    description=(
                        "Tipo: dockerfile|github_actions|gitlab_ci|helm_chart|"
                        "k8s_manifest|terraform|compose|ansible|kustomize."
                    ),
                ),
                "target": dict(_STR, description="Alvo (aplicação/serviço/módulo)."),
                "content": dict(_STR, description="Conteúdo do arquivo IaC gerado pelo agente."),
                "tool": dict(_STR, description="Ferramenta (docker/helm/kustomize/...; opcional)."),
                "spec": dict(_OBJ, description="Parâmetros/inputs do artefato (opcional)."),
                "status": dict(_STR, description="Status do artefato (opcional)."),
            },
            required=["kind", "target", "content"],
        ),
    ),
    "list_artifacts": _meta(
        "list_artifacts",
        "artifact:read",
        "artifact",
        "devops",
        "Lista artefatos IaC persistidos, com filtros opcionais.",
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
        "devops",
        "Retorna um artefato de infra-as-code persistido (Dockerfile/pipeline/chart/manifesto) por id.",
        _schema({"id": dict(_INT, description="Id do artefato.")}, required=["id"]),
    ),
    "delete_artifact": _meta(
        "delete_artifact",
        "artifact:write",
        "artifact",
        "devops",
        "Remove (soft-delete) um artefato de infra-as-code persistido por id; idempotente.",
        _schema({"id": dict(_INT, description="Id do artefato.")}, required=["id"]),
    ),
    # ── Pipelines ──────────────────────────────────────────────────────────── #
    "save_pipeline": _meta(
        "save_pipeline",
        "pipeline:write",
        "pipeline",
        "devops",
        "Persiste uma pipeline de CI/CD fornecida pelo agente (stages/triggers vêm do agente).",
        _schema(
            {
                "application": dict(_STR, description="Aplicação alvo."),
                "provider": dict(_STR, description="Provedor (github_actions/gitlab_ci/jenkins/...)."),
                "content": dict(_OBJ, description="Conteúdo da pipeline (stages/triggers/jobs)."),
                "status": dict(_STR, description="Status da pipeline (opcional)."),
            },
            required=["application", "provider"],
        ),
    ),
    "list_pipelines": _meta(
        "list_pipelines",
        "pipeline:read",
        "pipeline",
        "devops",
        "Lista pipelines persistidas, com filtros opcionais.",
        _schema(
            {
                "application": dict(_STR, description="Filtrar por aplicação (opcional)."),
                "provider": dict(_STR, description="Filtrar por provedor (opcional)."),
                "status": dict(_STR, description="Filtrar por status (opcional)."),
            }
        ),
    ),
    "get_pipeline": _meta(
        "get_pipeline",
        "pipeline:read",
        "pipeline",
        "devops",
        "Retorna uma pipeline de CI/CD persistida (stages/triggers/jobs) por id.",
        _schema({"id": dict(_INT, description="Id da pipeline.")}, required=["id"]),
    ),
    "update_pipeline": _meta(
        "update_pipeline",
        "pipeline:write",
        "pipeline",
        "devops",
        "Atualiza campos mutáveis de uma pipeline (provider/content/status).",
        _schema(
            {
                "id": dict(_INT, description="Id da pipeline."),
                "provider": dict(_STR, description="Novo provedor (opcional)."),
                "content": dict(_OBJ, description="Novo conteúdo (opcional)."),
                "status": dict(_STR, description="Novo status (opcional)."),
            },
            required=["id"],
        ),
    ),
    "delete_pipeline": _meta(
        "delete_pipeline",
        "pipeline:write",
        "pipeline",
        "devops",
        "Remove (soft-delete) uma pipeline de CI/CD persistida por id; idempotente.",
        _schema({"id": dict(_INT, description="Id da pipeline.")}, required=["id"]),
    ),
    # ── Deployments ────────────────────────────────────────────────────────── #
    "save_deployment": _meta(
        "save_deployment",
        "deployment:write",
        "deployment",
        "operational",
        "Persiste um deploy. Se strategy não vier, recomenda-a deterministicamente do ambiente.",
        _schema(
            {
                "application": dict(_STR, description="Aplicação alvo."),
                "environment": dict(_STR, description="Ambiente (dev/hml/prod)."),
                "version": dict(_STR, description="Versão / image tag."),
                "strategy": dict(
                    _STR, description="Estratégia (rolling/blue_green/canary/recreate; calculada se ausente)."
                ),
                "notes": dict(_STR, description="Notas do deploy (opcional)."),
                "meta": dict(_OBJ, description="Metadados adicionais (opcional)."),
                "status": dict(_STR, description="Status (default pending)."),
            },
            required=["application", "environment", "version"],
        ),
    ),
    "list_deployments": _meta(
        "list_deployments",
        "deployment:read",
        "deployment",
        "operational",
        "Lista deployments persistidos, com filtros opcionais.",
        _schema(
            {
                "application": dict(_STR, description="Filtrar por aplicação (opcional)."),
                "environment": dict(_STR, description="Filtrar por ambiente (opcional)."),
                "status": dict(_STR, description="Filtrar por status (opcional)."),
            }
        ),
    ),
    "get_deployment": _meta(
        "get_deployment",
        "deployment:read",
        "deployment",
        "operational",
        "Retorna um deployment persistido (aplicação/ambiente/versão/estratégia/status) por id.",
        _schema({"id": dict(_INT, description="Id do deployment.")}, required=["id"]),
    ),
    "update_deployment_status": _meta(
        "update_deployment_status",
        "deployment:write",
        "deployment",
        "operational",
        "Atualiza o status de um deployment (ex.: pending→running→succeeded/failed).",
        _schema(
            {
                "id": dict(_INT, description="Id do deployment."),
                "status": dict(_STR, description="Novo status."),
            },
            required=["id", "status"],
        ),
    ),
    "delete_deployment": _meta(
        "delete_deployment",
        "deployment:write",
        "deployment",
        "operational",
        "Remove (soft-delete) um deployment persistido por id; idempotente.",
        _schema({"id": dict(_INT, description="Id do deployment.")}, required=["id"]),
    ),
    # ── Environments (upsert por name) ─────────────────────────────────────── #
    "set_environment": _meta(
        "set_environment",
        "environment:write",
        "environment",
        "devops",
        "Registra (upsert) um ambiente/cluster de deploy com a config fornecida.",
        _schema(
            {
                "name": dict(_STR, description="Nome do ambiente (chave natural única)."),
                "kind": dict(_STR, description="Tipo (kubernetes/vm/serverless/docker/bare_metal)."),
                "region": dict(_STR, description="Região (opcional)."),
                "config": dict(_OBJ, description="Config do ambiente (cluster/namespace/limites)."),
                "status": dict(_STR, description="Status (opcional)."),
            },
            required=["name", "kind"],
        ),
    ),
    "list_environments": _meta(
        "list_environments",
        "environment:read",
        "environment",
        "devops",
        "Lista ambientes registrados, com filtros opcionais.",
        _schema(
            {
                "kind": dict(_STR, description="Filtrar por tipo (opcional)."),
                "status": dict(_STR, description="Filtrar por status (opcional)."),
            }
        ),
    ),
    "get_environment": _meta(
        "get_environment",
        "environment:read",
        "environment",
        "devops",
        "Retorna um ambiente/cluster de deploy registrado (tipo/região/config) pela chave natural name.",
        _schema({"name": dict(_STR, description="Nome do ambiente.")}, required=["name"]),
    ),
    "delete_environment": _meta(
        "delete_environment",
        "environment:write",
        "environment",
        "devops",
        "Remove (soft-delete) um ambiente/cluster de deploy registrado pela chave natural name; idempotente.",
        _schema({"name": dict(_STR, description="Nome do ambiente.")}, required=["name"]),
    ),
    # ── Service Configs (upsert por service) ───────────────────────────────── #
    "set_service_config": _meta(
        "set_service_config",
        "service_config:write",
        "service_config",
        "devops",
        "Define (upsert) a config de devops de um serviço com os settings fornecidos.",
        _schema(
            {
                "service": dict(_STR, description="Serviço alvo (chave natural única)."),
                "settings": dict(_OBJ, description="Settings (replicas/resources/env)."),
                "status": dict(_STR, description="Status (opcional)."),
            },
            required=["service", "settings"],
        ),
    ),
    "list_service_configs": _meta(
        "list_service_configs",
        "service_config:read",
        "service_config",
        "devops",
        "Lista service configs persistidas, com filtro opcional por status.",
        _schema({"status": dict(_STR, description="Filtrar por status (opcional).")}),
    ),
    "get_service_config": _meta(
        "get_service_config",
        "service_config:read",
        "service_config",
        "devops",
        "Retorna a config de devops de um serviço.",
        _schema({"service": dict(_STR, description="Serviço alvo.")}, required=["service"]),
    ),
    "delete_service_config": _meta(
        "delete_service_config",
        "service_config:write",
        "service_config",
        "devops",
        "Soft-delete da config de devops de um serviço.",
        _schema({"service": dict(_STR, description="Serviço alvo.")}, required=["service"]),
    ),
}

# devops-mcp não expõe tool tokenless: TODAS as tools tocam estado do tenant e exigem
# inner token válido (fail-closed). O liveness fica no /v1/health (sem tool).
_EXEMPT_TOOLS: frozenset[str] = frozenset()
# Denylist fail-safe: tools que retornam segredos NUNCA saem pelo gateway (CI-7).
_EXCLUDE_TOOLS: frozenset[str] = frozenset()

# Campos de policy repassados no /mcp/tools/list (o gateway lê estes campos).
_POLICY_FIELDS = ("capability", "required_scope", "resource_type", "data_domain")


# ── Verificação do inner Twin Token (STD-SEC-006 / CI-4/CI-5) ─────────────────


def _verify_inner_token(twin_token: str, settings: DevopsSettings) -> dict[str, Any]:
    """Re-verifica o inner Twin Token na PRÓPRIA audiência (mcp:devops-mcp).

    O gateway já verificou o front token; o backend é 'one more verified client'
    (defense in depth). RS256 via JWKS do platform-admin; audiência exata; jti
    obrigatório. Levanta em qualquer falha (fail-closed).
    """
    if not settings.mcp_twin_audience or not settings.url_admin_twin_jwks:
        raise PermissionError(
            "integração com o gateway não configurada: defina MCP_TWIN_AUDIENCE "
            "(mcp:devops-mcp) e URL_ADMIN_TWIN_JWKS (ver STD-SEC-006 / IT-006)."
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


async def _dispatch(name: str, args: dict[str, Any], store: DevopsStore) -> dict[str, Any]:
    """Despacha a chamada para a tool (async). O tenant NÃO viaja nos args (INV-3):
    o ``store`` já está ligado ao pool do tenant (resolvido dos claims do inner token)."""
    # ── Artifacts ──────────────────────────────────────────────────────────── #
    if name == "save_artifact":
        return await save_artifact(
            store,
            kind=args["kind"],
            target=args["target"],
            content=args["content"],
            tool=args.get("tool"),
            spec=args.get("spec"),
            status=args.get("status"),
        )
    if name == "list_artifacts":
        return await list_artifacts(
            store, kind=args.get("kind"), target=args.get("target"), limit=args.get("limit", 50)
        )
    if name == "get_artifact":
        return await get_artifact(store, artifact_id=args["id"])
    if name == "delete_artifact":
        return await delete_artifact(store, artifact_id=args["id"])
    # ── Pipelines ──────────────────────────────────────────────────────────── #
    if name == "save_pipeline":
        return await save_pipeline(
            store,
            application=args["application"],
            provider=args["provider"],
            content=args.get("content"),
            status=args.get("status"),
        )
    if name == "list_pipelines":
        return await list_pipelines(
            store,
            application=args.get("application"),
            provider=args.get("provider"),
            status=args.get("status"),
        )
    if name == "get_pipeline":
        return await get_pipeline(store, pipeline_id=args["id"])
    if name == "update_pipeline":
        return await update_pipeline(
            store,
            pipeline_id=args["id"],
            provider=args.get("provider"),
            content=args.get("content"),
            status=args.get("status"),
        )
    if name == "delete_pipeline":
        return await delete_pipeline(store, pipeline_id=args["id"])
    # ── Deployments ────────────────────────────────────────────────────────── #
    if name == "save_deployment":
        return await save_deployment(
            store,
            application=args["application"],
            environment=args["environment"],
            version=args["version"],
            strategy=args.get("strategy"),
            notes=args.get("notes"),
            meta=args.get("meta"),
            status=args.get("status", "pending"),
        )
    if name == "list_deployments":
        return await list_deployments(
            store,
            application=args.get("application"),
            environment=args.get("environment"),
            status=args.get("status"),
        )
    if name == "get_deployment":
        return await get_deployment(store, deployment_id=args["id"])
    if name == "update_deployment_status":
        return await update_deployment_status(store, deployment_id=args["id"], status=args["status"])
    if name == "delete_deployment":
        return await delete_deployment(store, deployment_id=args["id"])
    # ── Environments ───────────────────────────────────────────────────────── #
    if name == "set_environment":
        return await set_environment(
            store,
            name=args["name"],
            kind=args["kind"],
            region=args.get("region"),
            config=args.get("config"),
            status=args.get("status"),
        )
    if name == "list_environments":
        return await list_environments(store, kind=args.get("kind"), status=args.get("status"))
    if name == "get_environment":
        return await get_environment(store, name=args["name"])
    if name == "delete_environment":
        return await delete_environment(store, name=args["name"])
    # ── Service Configs ────────────────────────────────────────────────────── #
    if name == "set_service_config":
        return await set_service_config(
            store, service=args["service"], settings=args["settings"], status=args.get("status")
        )
    if name == "list_service_configs":
        return await list_service_configs(store, status=args.get("status"))
    if name == "get_service_config":
        return await get_service_config(store, service=args["service"])
    if name == "delete_service_config":
        return await delete_service_config(store, service=args["service"])
    raise KeyError(name)


# ── Tenant plumbing (credencial-zero) ─────────────────────────────────────────
# Bootstrap de schema roda UMA vez por tenant/processo (idempotente de qualquer forma).
_SCHEMA_READY: set[str] = set()
_SCHEMA_LOCK = asyncio.Lock()


async def _ensure_tenant_schema(settings: DevopsSettings, tenant_id: str) -> None:
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
    name: str, arguments: dict[str, Any], settings: DevopsSettings, tenant_id: str
) -> dict[str, Any]:
    """Abre a sessão tenant-scoped (credencial-zero), garante o schema e despacha."""
    await _ensure_tenant_schema(settings, tenant_id)
    async with for_tenant(tenant_id) as session:
        store = DevopsStore(session)
        return await _dispatch(name, arguments, store)


# ── HTTP Sidecar ──────────────────────────────────────────────────────────────


def _build_http_app(settings: DevopsSettings) -> FastAPI:
    """Cria o sidecar HTTP (health + bridge governado /mcp/tools/*).

    Stateless quanto a store: cada chamada abre uma sessão tenant-scoped
    (credencial-zero) a partir do tenant nos claims do inner token."""
    app = FastAPI(
        title="devops-mcp API",
        version="0.1.0",
        docs_url="/docs" if settings.docs_enabled else None,  # false em todo ambiente
        redoc_url=None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
    )

    @app.get("/v1/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "service": "devops-mcp", "tools": len(_TOOL_SCHEMAS)}

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

        # Toda tool do devops toca estado do tenant → inner token obrigatório (não há
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


def build_server() -> tuple[Any, DevopsSettings, FastAPI]:
    """Inicializa o MCP Server (stdio), settings e o sidecar HTTP.

    A persistência é tenant-scoped e resolvida por-request (credencial-zero).
    ``orm.configure(settings)`` registra a fonte admin (ADMIN_DB_*) usada para
    resolver o tenant → credencial do seu banco via PLATFORMS."""
    settings = get_settings()
    settings.enforce_security_invariants()  # fail-fast STD-SEC-001/004/006
    configure_logging(settings)  # logging estruturado JSON (STD-OBS-001)
    configure(settings)  # bootstrap credencial-zero (ORM-H-12): admin source p/ for_tenant
    http_app = _build_http_app(settings)
    _log.info("devops_mcp_ready tools=%d engine=%s", len(_TOOL_SCHEMAS), settings.DB_ENGINE)

    server: Server = Server("devops-mcp-server")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(name=name, description=meta["description"], inputSchema=meta["schema"])
            for name, meta in _TOOL_SCHEMAS.items()
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any] | None) -> list[TextContent]:
        # O transporte stdio não carrega o inner token (logo, sem tenant). devops-mcp
        # é gateway-only: a execução real entra pelo sidecar HTTP (/mcp/tools/call), onde
        # o tenant vem dos claims verificados. Aqui recusamos fail-closed (sem tenant).
        if name not in _TOOL_SCHEMAS:
            payload: dict[str, Any] = {"error": "unknown_tool", "tool": name}
        else:
            payload = {
                "error": "tenant_context_required",
                "tool": name,
                "detail": (
                    "devops-mcp é tenant-scoped e gateway-only; chame via o sidecar HTTP "
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
