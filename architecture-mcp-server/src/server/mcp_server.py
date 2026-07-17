"""Servidor MCP do architecture — sidecar kind=mcp_http, GATEWAY-READY (Model C).

Implementa o contrato de integração com o MCP Gateway central (platform-mcp-gateway):
  - docs/standards/STD-MCP-001-mcp-gateway-integration-contract.md  (CI-1..CI-11)
  - docs/standards/STD-SEC-006-token-model-c-inner-token.md          (inner token / audiência)

Pontos gateway-ready:
  1. /mcp/tools/list emite, por tool, inputSchema type=object + capability +
     required_scope + resource_type + data_domain (o gateway NÃO deriva por nome).
  2. /mcp/tools/call re-verifica o **inner Twin Token** (aud=mcp:architecture-mcp) via
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

NOTA: architecture-mcp é stateful — "o agente gera o conteúdo, a tool persiste": as
tools persistem propostas/modelos C4/blueprints/artefatos num MySQL via
`ArchitectureStore` (tenant-scoped, dual-db, credencial-zero). As antigas tools
`generate_*` viram *builders* determinísticos dobrados nos `save/set`. Não há backend
REST intermediário; o dispatcher recebe o store já ligado ao pool do tenant.
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
from ..config.settings import ArchitectureSettings, get_settings
from ..db.schema import ensure_schema
from ..db.store import ArchitectureStore
from ..tools import (
    delete_architecture_blueprint,
    delete_artifact,
    delete_c4_diagram,
    delete_solution_blueprint,
    generate_adr,
    generate_c4_diagram,
    generate_sequence_diagram,
    get_architecture_blueprint,
    get_artifact,
    get_c4_diagram,
    get_solution_blueprint,
    list_architecture_blueprints,
    list_artifacts,
    list_c4_diagrams,
    list_solution_blueprints,
    save_architecture_blueprint,
    save_artifact,
    save_solution_blueprint,
    set_c4_diagram,
    update_architecture_blueprint,
    update_solution_blueprint,
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
        "capability": f"architecture-mcp.{cap}",
        "required_scope": f"architecture-mcp:{scope}",
        "resource_type": rtype,
        "data_domain": domain,
        "schema": schema,
    }


_TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    # ── Architecture Blueprints ────────────────────────────────────────────── #
    "save_architecture_blueprint": _meta(
        "save_architecture_blueprint",
        "architecture_blueprint:write",
        "architecture_blueprint",
        "architecture",
        "Deriva a proposta de arquitetura dos inputs (estilo/táticas) e a persiste.",
        _schema(
            {
                "domain": dict(_STR, description="Domínio/negócio-alvo."),
                "constraints": dict(_ARR, description="Restrições técnicas/organizacionais (opcional)."),
                "quality_attributes": dict(
                    _ARR, description="Atributos de qualidade priorizados (opcional)."
                ),
                "architecture_name": dict(_STR, description="Nome da arquitetura (opcional)."),
                "status": dict(_STR, description="Status (opcional)."),
            },
            required=["domain"],
        ),
    ),
    "list_architecture_blueprints": _meta(
        "list_architecture_blueprints",
        "architecture_blueprint:read",
        "architecture_blueprint",
        "architecture",
        "Lista propostas de arquitetura persistidas, com filtros opcionais.",
        _schema(
            {
                "domain": dict(_STR, description="Filtrar por domínio (opcional)."),
                "status": dict(_STR, description="Filtrar por status (opcional)."),
            }
        ),
    ),
    "get_architecture_blueprint": _meta(
        "get_architecture_blueprint",
        "architecture_blueprint:read",
        "architecture_blueprint",
        "architecture",
        "Retorna uma proposta de arquitetura por id.",
        _schema({"id": dict(_INT, description="Id da proposta.")}, required=["id"]),
    ),
    "update_architecture_blueprint": _meta(
        "update_architecture_blueprint",
        "architecture_blueprint:write",
        "architecture_blueprint",
        "architecture",
        "Atualiza campos mutáveis de uma proposta (name/style/content/status).",
        _schema(
            {
                "id": dict(_INT, description="Id da proposta."),
                "name": dict(_STR, description="Novo nome (opcional)."),
                "style": dict(_STR, description="Novo estilo (opcional)."),
                "content": dict(_OBJ, description="Novo conteúdo (opcional)."),
                "status": dict(_STR, description="Novo status (opcional)."),
            },
            required=["id"],
        ),
    ),
    "delete_architecture_blueprint": _meta(
        "delete_architecture_blueprint",
        "architecture_blueprint:write",
        "architecture_blueprint",
        "architecture",
        "Soft-delete de uma proposta de arquitetura por id.",
        _schema({"id": dict(_INT, description="Id da proposta.")}, required=["id"]),
    ),
    # ── C4 Diagrams (upsert por system_name) ───────────────────────────────── #
    "set_c4_diagram": _meta(
        "set_c4_diagram",
        "c4_diagram:write",
        "c4_diagram",
        "architecture",
        "Deriva (ou aceita pronto) o modelo C4 e o persiste por sistema (upsert).",
        _schema(
            {
                "system_name": dict(_STR, description="Nome do sistema (chave natural única)."),
                "actors": dict(_ARR, description="Pessoas/sistemas externos (opcional)."),
                "containers": dict(_ARR, description="Aplicações/serviços internos (opcional)."),
                "relationships": dict(_ARR, description="Arestas {source,target} ou 'A -> B' (opcional)."),
                "model": dict(_OBJ, description="Modelo C4 pronto (opcional; sobrepõe o builder)."),
                "status": dict(_STR, description="Status (opcional)."),
            },
            required=["system_name"],
        ),
    ),
    "list_c4_diagrams": _meta(
        "list_c4_diagrams",
        "c4_diagram:read",
        "c4_diagram",
        "architecture",
        "Lista modelos C4 persistidos, com filtro opcional por status.",
        _schema({"status": dict(_STR, description="Filtrar por status (opcional).")}),
    ),
    "get_c4_diagram": _meta(
        "get_c4_diagram",
        "c4_diagram:read",
        "c4_diagram",
        "architecture",
        "Retorna o modelo C4 de um sistema.",
        _schema({"system_name": dict(_STR, description="Nome do sistema.")}, required=["system_name"]),
    ),
    "delete_c4_diagram": _meta(
        "delete_c4_diagram",
        "c4_diagram:write",
        "c4_diagram",
        "architecture",
        "Soft-delete do modelo C4 de um sistema.",
        _schema({"system_name": dict(_STR, description="Nome do sistema.")}, required=["system_name"]),
    ),
    # ── Solution Blueprints ────────────────────────────────────────────────── #
    "save_solution_blueprint": _meta(
        "save_solution_blueprint",
        "solution_blueprint:write",
        "solution_blueprint",
        "architecture",
        "Deriva o blueprint de solução dos requisitos (camadas/padrões/NFRs) e o persiste.",
        _schema(
            {
                "requirements": dict(_STR, description="Requisitos funcionais/de negócio."),
                "solution_name": dict(_STR, description="Nome da solução (opcional)."),
                "context": dict(_STR, description="Contexto adicional (opcional)."),
                "constraints": dict(_ARR, description="Restrições (opcional)."),
                "status": dict(_STR, description="Status (opcional)."),
            },
            required=["requirements"],
        ),
    ),
    "list_solution_blueprints": _meta(
        "list_solution_blueprints",
        "solution_blueprint:read",
        "solution_blueprint",
        "architecture",
        "Lista blueprints de solução persistidos, com filtros opcionais.",
        _schema(
            {
                "solution_name": dict(_STR, description="Filtrar por nome da solução (opcional)."),
                "status": dict(_STR, description="Filtrar por status (opcional)."),
            }
        ),
    ),
    "get_solution_blueprint": _meta(
        "get_solution_blueprint",
        "solution_blueprint:read",
        "solution_blueprint",
        "architecture",
        "Retorna um blueprint de solução por id.",
        _schema({"id": dict(_INT, description="Id do blueprint.")}, required=["id"]),
    ),
    "update_solution_blueprint": _meta(
        "update_solution_blueprint",
        "solution_blueprint:write",
        "solution_blueprint",
        "architecture",
        "Atualiza campos mutáveis de um blueprint de solução (context/content/status).",
        _schema(
            {
                "id": dict(_INT, description="Id do blueprint."),
                "context": dict(_STR, description="Novo contexto (opcional)."),
                "content": dict(_OBJ, description="Novo conteúdo (opcional)."),
                "status": dict(_STR, description="Novo status (opcional)."),
            },
            required=["id"],
        ),
    ),
    "delete_solution_blueprint": _meta(
        "delete_solution_blueprint",
        "solution_blueprint:write",
        "solution_blueprint",
        "architecture",
        "Soft-delete de um blueprint de solução por id.",
        _schema({"id": dict(_INT, description="Id do blueprint.")}, required=["id"]),
    ),
    # ── Artifacts (histórico append-only) ──────────────────────────────────── #
    "save_artifact": _meta(
        "save_artifact",
        "artifact:write",
        "artifact",
        "architecture",
        "Persiste um artefato de arquitetura (diagrama/ADR/nota) gerado pelo agente.",
        _schema(
            {
                "kind": dict(
                    _STR,
                    description=(
                        "Tipo: adr|c4|diagram|blueprint|proposal|decision|mermaid|plantuml|markdown|note."
                    ),
                ),
                "target": dict(_STR, description="Alvo (sistema/domínio/serviço)."),
                "content": dict(_STR, description="Texto/código gerado pelo agente."),
                "format": dict(_STR, description="Formato (mermaid/plantuml/markdown/json; opcional)."),
                "meta": dict(_OBJ, description="Metadados adicionais (opcional)."),
            },
            required=["kind", "target", "content"],
        ),
    ),
    "list_artifacts": _meta(
        "list_artifacts",
        "artifact:read",
        "artifact",
        "architecture",
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
        "architecture",
        "Retorna um artefato por id.",
        _schema({"id": dict(_INT, description="Id do artefato.")}, required=["id"]),
    ),
    "delete_artifact": _meta(
        "delete_artifact",
        "artifact:write",
        "artifact",
        "architecture",
        "Soft-delete de um artefato por id.",
        _schema({"id": dict(_INT, description="Id do artefato.")}, required=["id"]),
    ),
    # ── Geradores determinísticos (COMPUTE PURO — não persistem) ───────────── #
    # required_scope: os scopes existentes seguem `<resource_type>:<acao>` com
    # :read p/ consultas e :write p/ mutações do estado do tenant. Geradores não
    # LEEM nem GRAVAM estado — só formatam a spec em artefato de arquitetura —
    # então nenhum dos dois cabe. Escolha: nova ação `:generate` sobre
    # resource_type=`artifact` (o mesmo domínio dos artefatos persistidos):
    # least-privilege real (um token só de geração não abre leitura/escrita de
    # artefatos). data_domain=architecture.
    "generate_c4_diagram": _meta(
        "generate_c4_diagram",
        "artifact:generate",
        "artifact",
        "architecture",
        "Gera um diagrama C4 em Mermaid (context|container|component) determinístico a partir da spec.",
        _schema(
            {
                "level": dict(_STR, description="Nível: context|container|component."),
                "elements": dict(
                    _ARR,
                    description="Elementos [{name,type?,technology?,description?,id?}] ou nomes (str).",
                ),
                "relations": dict(
                    _ARR, description="Relações [{from,to,text?,technology?}] ou 'A -> B' (opcional)."
                ),
                "title": dict(_STR, description="Título do diagrama (opcional)."),
            },
            required=["level", "elements"],
        ),
    ),
    "generate_sequence_diagram": _meta(
        "generate_sequence_diagram",
        "artifact:generate",
        "artifact",
        "architecture",
        "Gera um diagrama de sequência em Mermaid determinístico a partir de participantes e mensagens.",
        _schema(
            {
                "participants": dict(
                    _ARR, description="Participantes [{name,alias?}] ou nomes (str) (opcional)."
                ),
                "messages": dict(_ARR, description="Mensagens [{from,to,text?,type?}]."),
                "title": dict(_STR, description="Título do diagrama (opcional)."),
            },
            required=["messages"],
        ),
    ),
    "generate_adr": _meta(
        "generate_adr",
        "artifact:generate",
        "artifact",
        "architecture",
        "Gera um ADR (Architecture Decision Record) em Markdown determinístico a partir da spec.",
        _schema(
            {
                "title": dict(_STR, description="Título da decisão."),
                "context": dict(_STR, description="Contexto/forças (str ou lista de bullets; opcional)."),
                "decision": dict(_STR, description="Decisão tomada (str ou lista; opcional)."),
                "consequences": dict(_STR, description="Consequências (str ou lista de bullets; opcional)."),
                "status": dict(_STR, description="Status (default Proposed)."),
                "number": dict(_INT, description="Número sequencial do ADR (opcional)."),
                "alternatives": dict(_ARR, description="Alternativas consideradas (opcional)."),
            },
            required=["title"],
        ),
    ),
}

# architecture-mcp não expõe tool tokenless: TODAS as tools tocam estado do tenant e
# exigem inner token válido (fail-closed). O liveness fica no /v1/health (sem tool).
_EXEMPT_TOOLS: frozenset[str] = frozenset()
# Denylist fail-safe: tools que retornam segredos NUNCA saem pelo gateway (CI-7).
_EXCLUDE_TOOLS: frozenset[str] = frozenset()

# Campos de policy repassados no /mcp/tools/list (o gateway lê estes campos).
_POLICY_FIELDS = ("capability", "required_scope", "resource_type", "data_domain")


# ── Verificação do inner Twin Token (STD-SEC-006 / CI-4/CI-5) ─────────────────


def _verify_inner_token(twin_token: str, settings: ArchitectureSettings) -> dict[str, Any]:
    """Re-verifica o inner Twin Token na PRÓPRIA audiência (mcp:architecture-mcp).

    O gateway já verificou o front token; o backend é 'one more verified client'
    (defense in depth). RS256 via JWKS do platform-admin; audiência exata; jti
    obrigatório. Levanta em qualquer falha (fail-closed).
    """
    if not settings.mcp_twin_audience or not settings.url_admin_twin_jwks:
        raise PermissionError(
            "integração com o gateway não configurada: defina MCP_TWIN_AUDIENCE "
            "(mcp:architecture-mcp) e URL_ADMIN_TWIN_JWKS (ver STD-SEC-006 / IT-006)."
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


async def _dispatch(name: str, args: dict[str, Any], store: ArchitectureStore) -> dict[str, Any]:
    """Despacha a chamada para a tool (async). O tenant NÃO viaja nos args (INV-3):
    o ``store`` já está ligado ao pool do tenant (resolvido dos claims do inner token)."""
    # ── Geradores (COMPUTE PURO: síncronos, ignoram o store — não persistem) ── #
    if name == "generate_c4_diagram":
        return generate_c4_diagram(args)
    if name == "generate_sequence_diagram":
        return generate_sequence_diagram(args)
    if name == "generate_adr":
        return generate_adr(args)
    # ── Architecture Blueprints ────────────────────────────────────────────── #
    if name == "save_architecture_blueprint":
        return await save_architecture_blueprint(
            store,
            domain=args["domain"],
            constraints=args.get("constraints"),
            quality_attributes=args.get("quality_attributes"),
            architecture_name=args.get("architecture_name", ""),
            status=args.get("status"),
        )
    if name == "list_architecture_blueprints":
        return await list_architecture_blueprints(store, domain=args.get("domain"), status=args.get("status"))
    if name == "get_architecture_blueprint":
        return await get_architecture_blueprint(store, blueprint_id=args["id"])
    if name == "update_architecture_blueprint":
        return await update_architecture_blueprint(
            store,
            blueprint_id=args["id"],
            name=args.get("name"),
            style=args.get("style"),
            content=args.get("content"),
            status=args.get("status"),
        )
    if name == "delete_architecture_blueprint":
        return await delete_architecture_blueprint(store, blueprint_id=args["id"])
    # ── C4 Diagrams ────────────────────────────────────────────────────────── #
    if name == "set_c4_diagram":
        return await set_c4_diagram(
            store,
            system_name=args["system_name"],
            actors=args.get("actors"),
            containers=args.get("containers"),
            relationships=args.get("relationships"),
            model=args.get("model"),
            status=args.get("status"),
        )
    if name == "list_c4_diagrams":
        return await list_c4_diagrams(store, status=args.get("status"))
    if name == "get_c4_diagram":
        return await get_c4_diagram(store, system_name=args["system_name"])
    if name == "delete_c4_diagram":
        return await delete_c4_diagram(store, system_name=args["system_name"])
    # ── Solution Blueprints ────────────────────────────────────────────────── #
    if name == "save_solution_blueprint":
        return await save_solution_blueprint(
            store,
            requirements=args["requirements"],
            solution_name=args.get("solution_name", "Solution"),
            context=args.get("context", ""),
            constraints=args.get("constraints"),
            status=args.get("status"),
        )
    if name == "list_solution_blueprints":
        return await list_solution_blueprints(
            store, solution_name=args.get("solution_name"), status=args.get("status")
        )
    if name == "get_solution_blueprint":
        return await get_solution_blueprint(store, blueprint_id=args["id"])
    if name == "update_solution_blueprint":
        return await update_solution_blueprint(
            store,
            blueprint_id=args["id"],
            context=args.get("context"),
            content=args.get("content"),
            status=args.get("status"),
        )
    if name == "delete_solution_blueprint":
        return await delete_solution_blueprint(store, blueprint_id=args["id"])
    # ── Artifacts ──────────────────────────────────────────────────────────── #
    if name == "save_artifact":
        return await save_artifact(
            store,
            kind=args["kind"],
            target=args["target"],
            content=args["content"],
            format=args.get("format"),
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


async def _ensure_tenant_schema(settings: ArchitectureSettings, tenant_id: str) -> None:
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
    name: str, arguments: dict[str, Any], settings: ArchitectureSettings, tenant_id: str
) -> dict[str, Any]:
    """Abre a sessão tenant-scoped (credencial-zero), garante o schema e despacha."""
    await _ensure_tenant_schema(settings, tenant_id)
    async with for_tenant(tenant_id) as session:
        store = ArchitectureStore(session)
        return await _dispatch(name, arguments, store)


# ── HTTP Sidecar ──────────────────────────────────────────────────────────────


def _build_http_app(settings: ArchitectureSettings) -> FastAPI:
    """Cria o sidecar HTTP (health + bridge governado /mcp/tools/*).

    Stateless quanto a store: cada chamada abre uma sessão tenant-scoped
    (credencial-zero) a partir do tenant nos claims do inner token."""
    app = FastAPI(
        title="architecture-mcp API",
        version="0.1.0",
        docs_url="/docs" if settings.docs_enabled else None,  # false em todo ambiente
        redoc_url=None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
    )

    @app.get("/v1/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "service": "architecture-mcp", "tools": len(_TOOL_SCHEMAS)}

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

        # Toda tool do architecture toca estado do tenant → inner token obrigatório (não há
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


def build_server() -> tuple[Any, ArchitectureSettings, FastAPI]:
    """Inicializa o MCP Server (stdio), settings e o sidecar HTTP.

    A persistência é tenant-scoped e resolvida por-request (credencial-zero).
    ``orm.configure(settings)`` registra a fonte admin (ADMIN_DB_*) usada para
    resolver o tenant → credencial do seu banco via PLATFORMS."""
    settings = get_settings()
    settings.enforce_security_invariants()  # fail-fast STD-SEC-001/004/006
    configure_logging(settings)  # logging estruturado JSON (STD-OBS-001)
    configure(settings)  # bootstrap credencial-zero (ORM-H-12): admin source p/ for_tenant
    http_app = _build_http_app(settings)
    _log.info("architecture_mcp_ready tools=%d engine=%s", len(_TOOL_SCHEMAS), settings.DB_ENGINE)

    server: Server = Server("architecture-mcp-server")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(name=name, description=meta["description"], inputSchema=meta["schema"])
            for name, meta in _TOOL_SCHEMAS.items()
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any] | None) -> list[TextContent]:
        # O transporte stdio não carrega o inner token (logo, sem tenant). architecture-mcp
        # é gateway-only: a execução real entra pelo sidecar HTTP (/mcp/tools/call), onde
        # o tenant vem dos claims verificados. Aqui recusamos fail-closed (sem tenant).
        if name not in _TOOL_SCHEMAS:
            payload: dict[str, Any] = {"error": "unknown_tool", "tool": name}
        else:
            payload = {
                "error": "tenant_context_required",
                "tool": name,
                "detail": (
                    "architecture-mcp é tenant-scoped e gateway-only; chame via o sidecar HTTP "
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
