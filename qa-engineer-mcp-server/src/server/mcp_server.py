"""Servidor MCP do qa-engineer — sidecar kind=mcp_http, GATEWAY-READY (Model C).

Implementa o contrato de integração com o MCP Gateway central (platform-mcp-gateway):
  - docs/standards/STD-MCP-001-mcp-gateway-integration-contract.md  (CI-1..CI-11)
  - docs/standards/STD-SEC-006-token-model-c-inner-token.md          (inner token / audiência)

Pontos gateway-ready:
  1. /mcp/tools/list emite, por tool, inputSchema type=object + capability +
     required_scope + resource_type + data_domain (o gateway NÃO deriva por nome).
  2. /mcp/tools/call re-verifica o **inner Twin Token** (aud=mcp:qa-engineer-mcp) via
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

NOTA: qa-engineer-mcp é stateful — "o agente gera o conteúdo, a tool persiste": as
tools persistem planos/casos/bugs/quality gates/artefatos num MySQL via
`QAEngineerStore` (tenant-scoped, dual-db, credencial-zero). Não há backend REST
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
from ..config.settings import QAEngineerSettings, get_settings
from ..db.schema import ensure_schema
from ..db.store import QAEngineerStore
from ..tools import (
    delete_artifact,
    delete_bug_report,
    delete_quality_gate,
    delete_test_case,
    delete_test_plan,
    get_artifact,
    get_bug_report,
    get_quality_gate,
    get_test_case,
    get_test_plan,
    list_artifacts,
    list_bug_reports,
    list_quality_gates,
    list_test_cases,
    list_test_plans,
    save_artifact,
    save_bug_report,
    save_test_case,
    save_test_plan,
    set_quality_gate,
    update_bug_status,
    update_test_case,
    update_test_plan,
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
        "capability": f"qa-engineer-mcp.{cap}",
        "required_scope": f"qa-engineer-mcp:{scope}",
        "resource_type": rtype,
        "data_domain": domain,
        "schema": schema,
    }


_TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    # ── Test Plans ─────────────────────────────────────────────────────────── #
    "save_test_plan": _meta(
        "save_test_plan",
        "test_plan:write",
        "test_plan",
        "qa-engineer",
        "Persiste um plano de teste fornecido pelo agente (o conteúdo vem do agente).",
        _schema(
            {
                "feature": dict(_STR, description="Funcionalidade alvo."),
                "content": dict(
                    _OBJ, description="Conteúdo do plano (objectives/levels/environments/schedule)."
                ),
                "scope": dict(_STR, description="Escopo (full/partial; default full)."),
                "team": dict(_STR, description="Time responsável (opcional)."),
                "status": dict(_STR, description="Status do plano (opcional)."),
            },
            required=["feature", "content"],
        ),
    ),
    "list_test_plans": _meta(
        "list_test_plans",
        "test_plan:read",
        "test_plan",
        "qa-engineer",
        "Lista planos de teste persistidos, com filtros opcionais.",
        _schema(
            {
                "feature": dict(_STR, description="Filtrar por funcionalidade (opcional)."),
                "status": dict(_STR, description="Filtrar por status (opcional)."),
            }
        ),
    ),
    "get_test_plan": _meta(
        "get_test_plan",
        "test_plan:read",
        "test_plan",
        "qa-engineer",
        "Retorna um plano de teste persistido (objetivos, níveis e ambientes) por id.",
        _schema({"id": dict(_INT, description="Id do plano.")}, required=["id"]),
    ),
    "update_test_plan": _meta(
        "update_test_plan",
        "test_plan:write",
        "test_plan",
        "qa-engineer",
        "Atualiza campos mutáveis de um plano de teste (scope/team/content/status).",
        _schema(
            {
                "id": dict(_INT, description="Id do plano."),
                "scope": dict(_STR, description="Novo escopo (opcional)."),
                "team": dict(_STR, description="Novo time (opcional)."),
                "content": dict(_OBJ, description="Novo conteúdo (opcional)."),
                "status": dict(_STR, description="Novo status (opcional)."),
            },
            required=["id"],
        ),
    ),
    "delete_test_plan": _meta(
        "delete_test_plan",
        "test_plan:write",
        "test_plan",
        "qa-engineer",
        "Soft-delete de um plano de teste por id.",
        _schema({"id": dict(_INT, description="Id do plano.")}, required=["id"]),
    ),
    # ── Test Cases ─────────────────────────────────────────────────────────── #
    "save_test_case": _meta(
        "save_test_case",
        "test_case:write",
        "test_case",
        "qa-engineer",
        "Persiste um caso de teste fornecido pelo agente (passos/dados vêm do agente).",
        _schema(
            {
                "feature": dict(_STR, description="Funcionalidade alvo."),
                "title": dict(_STR, description="Título do caso."),
                "steps": dict(_ARR, description="Passos do caso (lista)."),
                "test_type": dict(_STR, description="Tipo (functional/e2e/api/...; default functional)."),
                "priority": dict(_STR, description="Prioridade (high/medium/low; default medium)."),
                "preconditions": dict(_ARR, description="Pré-condições (opcional)."),
                "expected_result": dict(_STR, description="Resultado esperado (opcional)."),
                "test_data": dict(_OBJ, description="Dados de teste (opcional)."),
                "status": dict(_STR, description="Status (opcional)."),
            },
            required=["feature", "title", "steps"],
        ),
    ),
    "list_test_cases": _meta(
        "list_test_cases",
        "test_case:read",
        "test_case",
        "qa-engineer",
        "Lista casos de teste persistidos, com filtros opcionais.",
        _schema(
            {
                "feature": dict(_STR, description="Filtrar por funcionalidade (opcional)."),
                "test_type": dict(_STR, description="Filtrar por tipo (opcional)."),
                "status": dict(_STR, description="Filtrar por status (opcional)."),
            }
        ),
    ),
    "get_test_case": _meta(
        "get_test_case",
        "test_case:read",
        "test_case",
        "qa-engineer",
        "Retorna um caso de teste persistido (passos, dados e resultado esperado) por id.",
        _schema({"id": dict(_INT, description="Id do caso.")}, required=["id"]),
    ),
    "update_test_case": _meta(
        "update_test_case",
        "test_case:write",
        "test_case",
        "qa-engineer",
        "Atualiza campos mutáveis de um caso de teste.",
        _schema(
            {
                "id": dict(_INT, description="Id do caso."),
                "title": dict(_STR, description="Novo título (opcional)."),
                "test_type": dict(_STR, description="Novo tipo (opcional)."),
                "priority": dict(_STR, description="Nova prioridade (opcional)."),
                "preconditions": dict(_ARR, description="Novas pré-condições (opcional)."),
                "steps": dict(_ARR, description="Novos passos (opcional)."),
                "expected_result": dict(_STR, description="Novo resultado esperado (opcional)."),
                "test_data": dict(_OBJ, description="Novos dados de teste (opcional)."),
                "status": dict(_STR, description="Novo status (opcional)."),
            },
            required=["id"],
        ),
    ),
    "delete_test_case": _meta(
        "delete_test_case",
        "test_case:write",
        "test_case",
        "qa-engineer",
        "Remove (soft-delete) um caso de teste persistido por id; idempotente.",
        _schema({"id": dict(_INT, description="Id do caso.")}, required=["id"]),
    ),
    # ── Bug Reports ────────────────────────────────────────────────────────── #
    "save_bug_report": _meta(
        "save_bug_report",
        "bug_report:write",
        "bug_report",
        "operational",
        "Persiste um bug. Se severity/score não vierem, calcula-os de impact×frequency.",
        _schema(
            {
                "title": dict(_STR, description="Título do bug."),
                "impact": dict(_STR, description="Impacto (critical/high/medium/low; default medium)."),
                "frequency": dict(
                    _STR, description="Frequência (always/often/sometimes/rarely; default sometimes)."
                ),
                "severity": dict(_STR, description="Severidade P1–P4 (opcional; calculada se ausente)."),
                "score": dict(_NUM, description="Score (opcional; calculado se ausente)."),
                "steps": dict(_ARR, description="Passos para reproduzir (opcional)."),
                "description": dict(_STR, description="Descrição do bug (opcional)."),
                "status": dict(_STR, description="Status (default open)."),
            },
            required=["title"],
        ),
    ),
    "list_bug_reports": _meta(
        "list_bug_reports",
        "bug_report:read",
        "bug_report",
        "operational",
        "Lista bugs persistidos, com filtros opcionais.",
        _schema(
            {
                "severity": dict(_STR, description="Filtrar por severidade (opcional)."),
                "status": dict(_STR, description="Filtrar por status (opcional)."),
            }
        ),
    ),
    "get_bug_report": _meta(
        "get_bug_report",
        "bug_report:read",
        "bug_report",
        "operational",
        "Retorna um relatório de bug persistido (severidade, score e passos) por id.",
        _schema({"id": dict(_INT, description="Id do bug.")}, required=["id"]),
    ),
    "update_bug_status": _meta(
        "update_bug_status",
        "bug_report:write",
        "bug_report",
        "operational",
        "Atualiza o status de um bug (ex.: open→in_progress→closed).",
        _schema(
            {
                "id": dict(_INT, description="Id do bug."),
                "status": dict(_STR, description="Novo status."),
            },
            required=["id", "status"],
        ),
    ),
    "delete_bug_report": _meta(
        "delete_bug_report",
        "bug_report:write",
        "bug_report",
        "operational",
        "Remove (soft-delete) um relatório de bug persistido por id; idempotente.",
        _schema({"id": dict(_INT, description="Id do bug.")}, required=["id"]),
    ),
    # ── Quality Gates (upsert por service) ─────────────────────────────────── #
    "set_quality_gate": _meta(
        "set_quality_gate",
        "quality_gate:write",
        "quality_gate",
        "operational",
        "Define (upsert) o quality gate de um serviço com os thresholds fornecidos.",
        _schema(
            {
                "service": dict(_STR, description="Serviço alvo (chave natural única)."),
                "thresholds": dict(_OBJ, description="Thresholds do gate (mapa)."),
                "status": dict(_STR, description="Status do gate (opcional)."),
            },
            required=["service", "thresholds"],
        ),
    ),
    "list_quality_gates": _meta(
        "list_quality_gates",
        "quality_gate:read",
        "quality_gate",
        "operational",
        "Lista quality gates persistidos, com filtro opcional por status.",
        _schema({"status": dict(_STR, description="Filtrar por status (opcional).")}),
    ),
    "get_quality_gate": _meta(
        "get_quality_gate",
        "quality_gate:read",
        "quality_gate",
        "operational",
        "Retorna o quality gate persistido de um serviço (thresholds e status) pela chave natural do serviço.",
        _schema({"service": dict(_STR, description="Serviço alvo.")}, required=["service"]),
    ),
    "delete_quality_gate": _meta(
        "delete_quality_gate",
        "quality_gate:write",
        "quality_gate",
        "operational",
        "Soft-delete do quality gate de um serviço.",
        _schema({"service": dict(_STR, description="Serviço alvo.")}, required=["service"]),
    ),
    # ── Artifacts (histórico append-only) ──────────────────────────────────── #
    "save_artifact": _meta(
        "save_artifact",
        "artifact:write",
        "artifact",
        "qa-engineer",
        "Persiste um artefato de teste (código/cenário) gerado pelo agente.",
        _schema(
            {
                "kind": dict(
                    _STR,
                    description=(
                        "Tipo: e2e|api|unit|gherkin|playwright|cypress|postman|k6|"
                        "regression|smoke|uat|coverage|analysis|testability."
                    ),
                ),
                "target": dict(_STR, description="Alvo (feature/module/endpoint/service)."),
                "content": dict(_STR, description="Código/cenário gerado pelo agente."),
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
        "qa-engineer",
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
        "qa-engineer",
        "Retorna um artefato de QA persistido (código de teste, cenário ou evidência) por id.",
        _schema({"id": dict(_INT, description="Id do artefato.")}, required=["id"]),
    ),
    "delete_artifact": _meta(
        "delete_artifact",
        "artifact:write",
        "artifact",
        "qa-engineer",
        "Remove (soft-delete) um artefato de QA persistido (código de teste, cenário ou evidência) por id; idempotente.",
        _schema({"id": dict(_INT, description="Id do artefato.")}, required=["id"]),
    ),
}

# qa-engineer-mcp não expõe tool tokenless: TODAS as tools tocam estado do tenant e
# exigem inner token válido (fail-closed). O liveness fica no /v1/health (sem tool).
_EXEMPT_TOOLS: frozenset[str] = frozenset()
# Denylist fail-safe: tools que retornam segredos NUNCA saem pelo gateway (CI-7).
_EXCLUDE_TOOLS: frozenset[str] = frozenset()

# Campos de policy repassados no /mcp/tools/list (o gateway lê estes campos).
_POLICY_FIELDS = ("capability", "required_scope", "resource_type", "data_domain")


# ── Verificação do inner Twin Token (STD-SEC-006 / CI-4/CI-5) ─────────────────


def _verify_inner_token(twin_token: str, settings: QAEngineerSettings) -> dict[str, Any]:
    """Re-verifica o inner Twin Token na PRÓPRIA audiência (mcp:qa-engineer-mcp).

    O gateway já verificou o front token; o backend é 'one more verified client'
    (defense in depth). RS256 via JWKS do platform-admin; audiência exata; jti
    obrigatório. Levanta em qualquer falha (fail-closed).
    """
    if not settings.mcp_twin_audience or not settings.url_admin_twin_jwks:
        raise PermissionError(
            "integração com o gateway não configurada: defina MCP_TWIN_AUDIENCE "
            "(mcp:qa-engineer-mcp) e URL_ADMIN_TWIN_JWKS (ver STD-SEC-006 / IT-006)."
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


async def _dispatch(name: str, args: dict[str, Any], store: QAEngineerStore) -> dict[str, Any]:
    """Despacha a chamada para a tool (async). O tenant NÃO viaja nos args (INV-3):
    o ``store`` já está ligado ao pool do tenant (resolvido dos claims do inner token)."""
    # ── Test Plans ─────────────────────────────────────────────────────────── #
    if name == "save_test_plan":
        return await save_test_plan(
            store,
            feature=args["feature"],
            content=args["content"],
            scope=args.get("scope", "full"),
            team=args.get("team"),
            status=args.get("status"),
        )
    if name == "list_test_plans":
        return await list_test_plans(store, feature=args.get("feature"), status=args.get("status"))
    if name == "get_test_plan":
        return await get_test_plan(store, plan_id=args["id"])
    if name == "update_test_plan":
        return await update_test_plan(
            store,
            plan_id=args["id"],
            scope=args.get("scope"),
            team=args.get("team"),
            content=args.get("content"),
            status=args.get("status"),
        )
    if name == "delete_test_plan":
        return await delete_test_plan(store, plan_id=args["id"])
    # ── Test Cases ─────────────────────────────────────────────────────────── #
    if name == "save_test_case":
        return await save_test_case(
            store,
            feature=args["feature"],
            title=args["title"],
            steps=args["steps"],
            test_type=args.get("test_type", "functional"),
            priority=args.get("priority", "medium"),
            preconditions=args.get("preconditions"),
            expected_result=args.get("expected_result"),
            test_data=args.get("test_data"),
            status=args.get("status"),
        )
    if name == "list_test_cases":
        return await list_test_cases(
            store,
            feature=args.get("feature"),
            test_type=args.get("test_type"),
            status=args.get("status"),
        )
    if name == "get_test_case":
        return await get_test_case(store, case_id=args["id"])
    if name == "update_test_case":
        return await update_test_case(
            store,
            case_id=args["id"],
            title=args.get("title"),
            test_type=args.get("test_type"),
            priority=args.get("priority"),
            preconditions=args.get("preconditions"),
            steps=args.get("steps"),
            expected_result=args.get("expected_result"),
            test_data=args.get("test_data"),
            status=args.get("status"),
        )
    if name == "delete_test_case":
        return await delete_test_case(store, case_id=args["id"])
    # ── Bug Reports ────────────────────────────────────────────────────────── #
    if name == "save_bug_report":
        return await save_bug_report(
            store,
            title=args["title"],
            impact=args.get("impact", "medium"),
            frequency=args.get("frequency", "sometimes"),
            severity=args.get("severity"),
            score=args.get("score"),
            steps=args.get("steps"),
            description=args.get("description"),
            status=args.get("status", "open"),
        )
    if name == "list_bug_reports":
        return await list_bug_reports(store, severity=args.get("severity"), status=args.get("status"))
    if name == "get_bug_report":
        return await get_bug_report(store, bug_id=args["id"])
    if name == "update_bug_status":
        return await update_bug_status(store, bug_id=args["id"], status=args["status"])
    if name == "delete_bug_report":
        return await delete_bug_report(store, bug_id=args["id"])
    # ── Quality Gates ──────────────────────────────────────────────────────── #
    if name == "set_quality_gate":
        return await set_quality_gate(
            store, service=args["service"], thresholds=args["thresholds"], status=args.get("status")
        )
    if name == "list_quality_gates":
        return await list_quality_gates(store, status=args.get("status"))
    if name == "get_quality_gate":
        return await get_quality_gate(store, service=args["service"])
    if name == "delete_quality_gate":
        return await delete_quality_gate(store, service=args["service"])
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


async def _ensure_tenant_schema(settings: QAEngineerSettings, tenant_id: str) -> None:
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
    name: str, arguments: dict[str, Any], settings: QAEngineerSettings, tenant_id: str
) -> dict[str, Any]:
    """Abre a sessão tenant-scoped (credencial-zero), garante o schema e despacha."""
    await _ensure_tenant_schema(settings, tenant_id)
    async with for_tenant(tenant_id) as session:
        store = QAEngineerStore(session)
        return await _dispatch(name, arguments, store)


# ── HTTP Sidecar ──────────────────────────────────────────────────────────────


def _build_http_app(settings: QAEngineerSettings) -> FastAPI:
    """Cria o sidecar HTTP (health + bridge governado /mcp/tools/*).

    Stateless quanto a store: cada chamada abre uma sessão tenant-scoped
    (credencial-zero) a partir do tenant nos claims do inner token."""
    app = FastAPI(
        title="qa-engineer-mcp API",
        version="0.1.0",
        docs_url="/docs" if settings.docs_enabled else None,  # false em todo ambiente
        redoc_url=None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
    )

    @app.get("/v1/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "service": "qa-engineer-mcp", "tools": len(_TOOL_SCHEMAS)}

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

        # Toda tool do qa-engineer toca estado do tenant → inner token obrigatório (não há
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


def build_server() -> tuple[Any, QAEngineerSettings, FastAPI]:
    """Inicializa o MCP Server (stdio), settings e o sidecar HTTP.

    A persistência é tenant-scoped e resolvida por-request (credencial-zero).
    ``orm.configure(settings)`` registra a fonte admin (ADMIN_DB_*) usada para
    resolver o tenant → credencial do seu banco via PLATFORMS."""
    settings = get_settings()
    settings.enforce_security_invariants()  # fail-fast STD-SEC-001/004/006
    configure_logging(settings)  # logging estruturado JSON (STD-OBS-001)
    configure(settings)  # bootstrap credencial-zero (ORM-H-12): admin source p/ for_tenant
    http_app = _build_http_app(settings)
    _log.info("qa_engineer_mcp_ready tools=%d engine=%s", len(_TOOL_SCHEMAS), settings.DB_ENGINE)

    server: Server = Server("qa-engineer-mcp-server")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(name=name, description=meta["description"], inputSchema=meta["schema"])
            for name, meta in _TOOL_SCHEMAS.items()
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any] | None) -> list[TextContent]:
        # O transporte stdio não carrega o inner token (logo, sem tenant). qa-engineer-mcp
        # é gateway-only: a execução real entra pelo sidecar HTTP (/mcp/tools/call), onde
        # o tenant vem dos claims verificados. Aqui recusamos fail-closed (sem tenant).
        if name not in _TOOL_SCHEMAS:
            payload: dict[str, Any] = {"error": "unknown_tool", "tool": name}
        else:
            payload = {
                "error": "tenant_context_required",
                "tool": name,
                "detail": (
                    "qa-engineer-mcp é tenant-scoped e gateway-only; chame via o sidecar HTTP "
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
