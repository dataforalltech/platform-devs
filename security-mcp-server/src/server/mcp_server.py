"""Servidor MCP do security — sidecar kind=mcp_http, GATEWAY-READY (Model C).

Implementa o contrato de integração com o MCP Gateway central (platform-mcp-gateway):
  - docs/standards/STD-MCP-001-mcp-gateway-integration-contract.md  (CI-1..CI-11)
  - docs/standards/STD-SEC-006-token-model-c-inner-token.md          (inner token / audiência)

Pontos gateway-ready:
  1. /mcp/tools/list emite, por tool, inputSchema type=object + capability +
     required_scope + resource_type + data_domain (o gateway NÃO deriva por nome).
  2. /mcp/tools/call re-verifica o **inner Twin Token** (aud=mcp:security-mcp) via
     JWKS do platform-admin, na PRÓPRIA audiência (defense in depth — CI-4/CI-5). O
     inner token chega em params._meta.twin_token.
  3. tenant_id vem SEMPRE dos claims do token verificado — nunca de argumento do
     cliente (SEC-035 / INV-3).
  4. _EXEMPT_TOOLS (tokenless) e _EXCLUDE_TOOLS (denylist fail-safe).
  5. /docs desabilitado (DOCS_ENABLED=false — HTTP-01).

Transporte: stdio (primário, MCP) + sidecar HTTP (:MCP_PORT, default 7100):
  GET  /v1/health        — liveness (health_path do registro, sem token)
  GET  /mcp/tools/list   — catálogo governado (com metadados de policy)
  POST /mcp/tools/call   — execução (inner token obrigatório, exceto _EXEMPT_TOOLS)

NOTA: security-mcp é stateful — "o agente gera o conteúdo, a tool persiste": as tools
persistem modelos de ameaças/controles/avaliações CVSS/artefatos num MySQL via
`SecurityStore` (tenant-scoped, dual-db, credencial-zero). Não há backend REST
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
from ..config.settings import SecuritySettings, get_settings
from ..db.schema import ensure_schema
from ..db.store import SecurityStore
from ..tools import (
    delete_cvss_assessment,
    delete_security_artifact,
    delete_security_control,
    delete_threat_model,
    generate_api_security_spec,
    generate_compliance_report,
    generate_security_controls,
    generate_security_handbook,
    get_cvss_assessment,
    get_security_artifact,
    get_security_control,
    get_threat_model,
    list_cvss_assessments,
    list_security_artifacts,
    list_security_controls,
    list_threat_models,
    save_cvss_assessment,
    save_security_artifact,
    save_threat_model,
    set_security_control,
    update_threat_model,
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
        "capability": f"security-mcp.{cap}",
        "required_scope": f"security-mcp:{scope}",
        "resource_type": rtype,
        "data_domain": domain,
        "schema": schema,
    }


_TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    # ── Threat Models ──────────────────────────────────────────────────────── #
    "save_threat_model": _meta(
        "save_threat_model",
        "threat_model:write",
        "threat_model",
        "security",
        "Persiste um modelo de ameaças fornecido pelo agente (as ameaças vêm do agente).",
        _schema(
            {
                "system_name": dict(_STR, description="Sistema alvo."),
                "methodology": dict(_STR, description="Metodologia (STRIDE/PASTA/...; default STRIDE)."),
                "title": dict(_STR, description="Título do modelo (opcional)."),
                "components": dict(_ARR, description="Componentes do sistema (opcional)."),
                "threats": dict(_ARR, description="Ameaças identificadas pelo agente (opcional)."),
                "summary": dict(_STR, description="Sumário/escopo da avaliação (opcional)."),
                "status": dict(_STR, description="Status do modelo (opcional)."),
            },
            required=["system_name"],
        ),
    ),
    "list_threat_models": _meta(
        "list_threat_models",
        "threat_model:read",
        "threat_model",
        "security",
        "Lista modelos de ameaças persistidos, com filtros opcionais.",
        _schema(
            {
                "system_name": dict(_STR, description="Filtrar por sistema (opcional)."),
                "status": dict(_STR, description="Filtrar por status (opcional)."),
            }
        ),
    ),
    "get_threat_model": _meta(
        "get_threat_model",
        "threat_model:read",
        "threat_model",
        "security",
        "Retorna um modelo de ameaças persistido (componentes/ameaças/sumário) por id.",
        _schema({"id": dict(_INT, description="Id do modelo.")}, required=["id"]),
    ),
    "update_threat_model": _meta(
        "update_threat_model",
        "threat_model:write",
        "threat_model",
        "security",
        "Atualiza campos mutáveis de um modelo de ameaças.",
        _schema(
            {
                "id": dict(_INT, description="Id do modelo."),
                "methodology": dict(_STR, description="Nova metodologia (opcional)."),
                "title": dict(_STR, description="Novo título (opcional)."),
                "components": dict(_ARR, description="Novos componentes (opcional)."),
                "threats": dict(_ARR, description="Novas ameaças (opcional)."),
                "summary": dict(_STR, description="Novo sumário (opcional)."),
                "status": dict(_STR, description="Novo status (opcional)."),
            },
            required=["id"],
        ),
    ),
    "delete_threat_model": _meta(
        "delete_threat_model",
        "threat_model:write",
        "threat_model",
        "security",
        "Soft-delete de um modelo de ameaças por id.",
        _schema({"id": dict(_INT, description="Id do modelo.")}, required=["id"]),
    ),
    # ── Security Controls (upsert por (system_name, control_key)) ───────────────── #
    "set_security_control": _meta(
        "set_security_control",
        "security_control:write",
        "security_control",
        "security",
        "Define (upsert) um controle de segurança por (system_name, control_key).",
        _schema(
            {
                "system_name": dict(_STR, description="Sistema alvo (parte da chave natural)."),
                "control_key": dict(_STR, description="Chave do controle (parte da chave natural)."),
                "name": dict(_STR, description="Nome do controle (opcional)."),
                "control_type": dict(_STR, description="Tipo (technical/operational; opcional)."),
                "framework_ref": dict(_STR, description="Referência de framework (nist_csf/...; opcional)."),
                "details": dict(_OBJ, description="Detalhes do controle (opcional)."),
                "status": dict(_STR, description="Status do controle (opcional)."),
            },
            required=["system_name", "control_key"],
        ),
    ),
    "list_security_controls": _meta(
        "list_security_controls",
        "security_control:read",
        "security_control",
        "security",
        "Lista controles de segurança persistidos, com filtros opcionais.",
        _schema(
            {
                "system_name": dict(_STR, description="Filtrar por sistema (opcional)."),
                "status": dict(_STR, description="Filtrar por status (opcional)."),
            }
        ),
    ),
    "get_security_control": _meta(
        "get_security_control",
        "security_control:read",
        "security_control",
        "security",
        "Retorna um controle de segurança por (system_name, control_key).",
        _schema(
            {
                "system_name": dict(_STR, description="Sistema alvo."),
                "control_key": dict(_STR, description="Chave do controle."),
            },
            required=["system_name", "control_key"],
        ),
    ),
    "delete_security_control": _meta(
        "delete_security_control",
        "security_control:write",
        "security_control",
        "security",
        "Soft-delete de um controle de segurança por (system_name, control_key).",
        _schema(
            {
                "system_name": dict(_STR, description="Sistema alvo."),
                "control_key": dict(_STR, description="Chave do controle."),
            },
            required=["system_name", "control_key"],
        ),
    ),
    # ── CVSS Assessments ───────────────────────────────────────────────────── #
    "save_cvss_assessment": _meta(
        "save_cvss_assessment",
        "cvss:write",
        "cvss",
        "security",
        "Persiste uma avaliação CVSS. Se score/severity/metrics não vierem, calcula-os do vetor.",
        _schema(
            {
                "vector": dict(_STR, description="Vetor CVSS 3.1 (ex: CVSS:3.1/AV:N/AC:L/...)."),
                "label": dict(_STR, description="Rótulo/CVE da vulnerabilidade (opcional)."),
                "base_score": dict(_NUM, description="Score (opcional; calculado se ausente)."),
                "severity": dict(_STR, description="Severidade (opcional; calculada se ausente)."),
                "metrics": dict(_OBJ, description="Métricas do vetor (opcional; calculadas se ausente)."),
                "status": dict(_STR, description="Status (opcional)."),
            },
            required=["vector"],
        ),
    ),
    "list_cvss_assessments": _meta(
        "list_cvss_assessments",
        "cvss:read",
        "cvss",
        "security",
        "Lista avaliações CVSS persistidas, com filtros opcionais.",
        _schema(
            {
                "severity": dict(_STR, description="Filtrar por severidade (opcional)."),
                "label": dict(_STR, description="Filtrar por rótulo/CVE (opcional)."),
            }
        ),
    ),
    "get_cvss_assessment": _meta(
        "get_cvss_assessment",
        "cvss:read",
        "cvss",
        "security",
        "Retorna uma avaliação CVSS persistida (vetor/score/severidade/métricas) por id.",
        _schema({"id": dict(_INT, description="Id da avaliação.")}, required=["id"]),
    ),
    "delete_cvss_assessment": _meta(
        "delete_cvss_assessment",
        "cvss:write",
        "cvss",
        "security",
        "Soft-delete de uma avaliação CVSS por id.",
        _schema({"id": dict(_INT, description="Id da avaliação.")}, required=["id"]),
    ),
    # ── Security Artifacts (histórico append-only) ─────────────────────────── #
    "save_security_artifact": _meta(
        "save_security_artifact",
        "artifact:write",
        "artifact",
        "security",
        "Persiste um artefato de segurança (relatório/scan) gerado pelo agente.",
        _schema(
            {
                "kind": dict(
                    _STR,
                    description=(
                        "Tipo: incident_plan|attack_surface|compliance|code_review|"
                        "dep_risk|secrets_scan|headers|password_policy."
                    ),
                ),
                "target": dict(_STR, description="Alvo (sistema/serviço/endpoint/arquivo)."),
                "content": dict(_STR, description="Relatório/texto gerado pelo agente (opcional)."),
                "meta": dict(_OBJ, description="Metadados adicionais (opcional)."),
            },
            required=["kind", "target"],
        ),
    ),
    "list_security_artifacts": _meta(
        "list_security_artifacts",
        "artifact:read",
        "artifact",
        "security",
        "Lista artefatos de segurança persistidos, com filtros opcionais.",
        _schema(
            {
                "kind": dict(_STR, description="Filtrar por tipo (opcional)."),
                "target": dict(_STR, description="Filtrar por alvo (opcional)."),
                "limit": dict(_INT, description="Máximo de registros (default 50)."),
            }
        ),
    ),
    "get_security_artifact": _meta(
        "get_security_artifact",
        "artifact:read",
        "artifact",
        "security",
        "Retorna um artefato de segurança por id.",
        _schema({"id": dict(_INT, description="Id do artefato.")}, required=["id"]),
    ),
    "delete_security_artifact": _meta(
        "delete_security_artifact",
        "artifact:write",
        "artifact",
        "security",
        "Soft-delete de um artefato de segurança por id.",
        _schema({"id": dict(_INT, description="Id do artefato.")}, required=["id"]),
    ),
    # ── Geradores determinísticos (COMPUTE PURO — não persistem) ───────────── #
    # required_scope: os scopes existentes seguem `<resource_type>:<acao>` com
    # :read p/ consultas e :write p/ mutações do estado do tenant. Geradores não
    # LEEM nem GRAVAM estado — só computam conteúdo de segurança — então nenhum dos
    # dois cabe. Escolha: nova ação `:generate` sobre resource_type=`artifact` (o
    # mesmo domínio dos artefatos de segurança produzidos): least-privilege real (um
    # token só de geração não abre leitura/escrita de artefatos persistidos).
    "generate_security_controls": _meta(
        "generate_security_controls",
        "artifact:generate",
        "artifact",
        "security",
        "Gera uma matriz de controles de segurança (controles × assets) determinística a partir da spec.",
        _schema(
            {
                "framework": dict(_STR, description="Framework de referência (nist_csf/iso_27001/cis/...)."),
                "assets": dict(_ARR, description="Assets [str | {name}] que compõem as colunas (opcional)."),
                "controls": dict(
                    _ARR,
                    description="Controles [{key|control_key,name?,category?,framework_ref?,applies_to?}].",
                ),
            },
            required=["framework", "controls"],
        ),
    ),
    "generate_api_security_spec": _meta(
        "generate_api_security_spec",
        "artifact:generate",
        "artifact",
        "security",
        "Gera um spec de segurança de API (YAML) determinístico a partir de endpoints/auth/ameaças.",
        _schema(
            {
                "endpoints": dict(
                    _ARR,
                    description="Endpoints [{path,method?,auth_required?,scopes?}].",
                ),
                "auth": dict(_OBJ, description="Esquema de auth (string ou objeto; default bearer_jwt)."),
                "threats": dict(_ARR, description="Ameaças [str | {id?,description,...}] (opcional)."),
                "title": dict(_STR, description="Título do spec (opcional)."),
            },
            required=["endpoints"],
        ),
    ),
    "generate_compliance_report": _meta(
        "generate_compliance_report",
        "artifact:generate",
        "artifact",
        "security",
        "Gera um relatório de compliance (markdown) determinístico com sumário e índice de conformidade.",
        _schema(
            {
                "standard": dict(_STR, description="Padrão avaliado (SOC2/ISO27001/LGPD/...)."),
                "findings": dict(
                    _ARR,
                    description="Achados [{control,status,note?}]; status ex.: pass|partial|fail|na.",
                ),
                "title": dict(_STR, description="Título do relatório (opcional)."),
            },
            required=["standard", "findings"],
        ),
    ),
    "generate_security_handbook": _meta(
        "generate_security_handbook",
        "artifact:generate",
        "artifact",
        "security",
        "Gera um handbook de segurança (markdown com índice) determinístico a partir das seções.",
        _schema(
            {
                "sections": dict(_ARR, description="Seções [{title,content?,items?}]."),
                "title": dict(_STR, description="Título do handbook (default 'Security Handbook')."),
            },
            required=["sections"],
        ),
    ),
}

# security-mcp não expõe tool tokenless: TODAS as tools tocam estado do tenant e
# exigem inner token válido (fail-closed). O liveness fica no /v1/health (sem tool).
_EXEMPT_TOOLS: frozenset[str] = frozenset()
# Denylist fail-safe: tools que retornam segredos NUNCA saem pelo gateway (CI-7).
_EXCLUDE_TOOLS: frozenset[str] = frozenset()

# Campos de policy repassados no /mcp/tools/list (o gateway lê estes campos).
_POLICY_FIELDS = ("capability", "required_scope", "resource_type", "data_domain")


# ── Verificação do inner Twin Token (STD-SEC-006 / CI-4/CI-5) ─────────────────


def _verify_inner_token(twin_token: str, settings: SecuritySettings) -> dict[str, Any]:
    """Re-verifica o inner Twin Token na PRÓPRIA audiência (mcp:security-mcp).

    O gateway já verificou o front token; o backend é 'one more verified client'
    (defense in depth). RS256 via JWKS do platform-admin; audiência exata; jti
    obrigatório. Levanta em qualquer falha (fail-closed).
    """
    if not settings.mcp_twin_audience or not settings.url_admin_twin_jwks:
        raise PermissionError(
            "integração com o gateway não configurada: defina MCP_TWIN_AUDIENCE "
            "(mcp:security-mcp) e URL_ADMIN_TWIN_JWKS (ver STD-SEC-006 / IT-006)."
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


async def _dispatch(name: str, args: dict[str, Any], store: SecurityStore) -> dict[str, Any]:
    """Despacha a chamada para a tool (async). O tenant NÃO viaja nos args (INV-3):
    o ``store`` já está ligado ao pool do tenant (resolvido dos claims do inner token)."""
    # ── Geradores (COMPUTE PURO: síncronos, ignoram o store — não persistem) ── #
    if name == "generate_security_controls":
        return generate_security_controls(args)
    if name == "generate_api_security_spec":
        return generate_api_security_spec(args)
    if name == "generate_compliance_report":
        return generate_compliance_report(args)
    if name == "generate_security_handbook":
        return generate_security_handbook(args)
    # ── Threat Models ──────────────────────────────────────────────────────── #
    if name == "save_threat_model":
        return await save_threat_model(
            store,
            system_name=args["system_name"],
            methodology=args.get("methodology", "STRIDE"),
            title=args.get("title"),
            components=args.get("components"),
            threats=args.get("threats"),
            summary=args.get("summary"),
            status=args.get("status"),
        )
    if name == "list_threat_models":
        return await list_threat_models(store, system_name=args.get("system_name"), status=args.get("status"))
    if name == "get_threat_model":
        return await get_threat_model(store, model_id=args["id"])
    if name == "update_threat_model":
        return await update_threat_model(
            store,
            model_id=args["id"],
            methodology=args.get("methodology"),
            title=args.get("title"),
            components=args.get("components"),
            threats=args.get("threats"),
            summary=args.get("summary"),
            status=args.get("status"),
        )
    if name == "delete_threat_model":
        return await delete_threat_model(store, model_id=args["id"])
    # ── Security Controls ──────────────────────────────────────────────────── #
    if name == "set_security_control":
        return await set_security_control(
            store,
            system_name=args["system_name"],
            control_key=args["control_key"],
            name=args.get("name"),
            control_type=args.get("control_type"),
            framework_ref=args.get("framework_ref"),
            details=args.get("details"),
            status=args.get("status"),
        )
    if name == "list_security_controls":
        return await list_security_controls(
            store, system_name=args.get("system_name"), status=args.get("status")
        )
    if name == "get_security_control":
        return await get_security_control(
            store, system_name=args["system_name"], control_key=args["control_key"]
        )
    if name == "delete_security_control":
        return await delete_security_control(
            store, system_name=args["system_name"], control_key=args["control_key"]
        )
    # ── CVSS Assessments ───────────────────────────────────────────────────── #
    if name == "save_cvss_assessment":
        return await save_cvss_assessment(
            store,
            vector=args["vector"],
            label=args.get("label"),
            base_score=args.get("base_score"),
            severity=args.get("severity"),
            metrics=args.get("metrics"),
            status=args.get("status"),
        )
    if name == "list_cvss_assessments":
        return await list_cvss_assessments(store, severity=args.get("severity"), label=args.get("label"))
    if name == "get_cvss_assessment":
        return await get_cvss_assessment(store, assessment_id=args["id"])
    if name == "delete_cvss_assessment":
        return await delete_cvss_assessment(store, assessment_id=args["id"])
    # ── Security Artifacts ─────────────────────────────────────────────────── #
    if name == "save_security_artifact":
        return await save_security_artifact(
            store,
            kind=args["kind"],
            target=args["target"],
            content=args.get("content"),
            meta=args.get("meta"),
        )
    if name == "list_security_artifacts":
        return await list_security_artifacts(
            store, kind=args.get("kind"), target=args.get("target"), limit=args.get("limit", 50)
        )
    if name == "get_security_artifact":
        return await get_security_artifact(store, artifact_id=args["id"])
    if name == "delete_security_artifact":
        return await delete_security_artifact(store, artifact_id=args["id"])
    raise KeyError(name)


# ── Tenant plumbing (credencial-zero) ─────────────────────────────────────────
# Bootstrap de schema roda UMA vez por tenant/processo (idempotente de qualquer forma).
_SCHEMA_READY: set[str] = set()
_SCHEMA_LOCK = asyncio.Lock()


async def _ensure_tenant_schema(settings: SecuritySettings, tenant_id: str) -> None:
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
    name: str, arguments: dict[str, Any], settings: SecuritySettings, tenant_id: str
) -> dict[str, Any]:
    """Abre a sessão tenant-scoped (credencial-zero), garante o schema e despacha."""
    await _ensure_tenant_schema(settings, tenant_id)
    async with for_tenant(tenant_id) as session:
        store = SecurityStore(session)
        return await _dispatch(name, arguments, store)


# ── HTTP Sidecar ──────────────────────────────────────────────────────────────


def _build_http_app(settings: SecuritySettings) -> FastAPI:
    """Cria o sidecar HTTP (health + bridge governado /mcp/tools/*).

    Stateless quanto a store: cada chamada abre uma sessão tenant-scoped
    (credencial-zero) a partir do tenant nos claims do inner token."""
    app = FastAPI(
        title="security-mcp API",
        version="0.1.0",
        docs_url="/docs" if settings.docs_enabled else None,  # false em todo ambiente
        redoc_url=None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
    )

    @app.get("/v1/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "service": "security-mcp", "tools": len(_TOOL_SCHEMAS)}

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

        # Toda tool do security toca estado do tenant → inner token obrigatório (não há
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


def build_server() -> tuple[Any, SecuritySettings, FastAPI]:
    """Inicializa o MCP Server (stdio), settings e o sidecar HTTP.

    A persistência é tenant-scoped e resolvida por-request (credencial-zero).
    ``orm.configure(settings)`` registra a fonte admin (ADMIN_DB_*) usada para
    resolver o tenant → credencial do seu banco via PLATFORMS."""
    settings = get_settings()
    settings.enforce_security_invariants()  # fail-fast STD-SEC-001/004/006
    configure_logging(settings)  # logging estruturado JSON (STD-OBS-001)
    configure(settings)  # bootstrap credencial-zero (ORM-H-12): admin source p/ for_tenant
    http_app = _build_http_app(settings)
    _log.info("security_mcp_ready tools=%d engine=%s", len(_TOOL_SCHEMAS), settings.DB_ENGINE)

    server: Server = Server("security-mcp-server")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(name=name, description=meta["description"], inputSchema=meta["schema"])
            for name, meta in _TOOL_SCHEMAS.items()
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any] | None) -> list[TextContent]:
        # O transporte stdio não carrega o inner token (logo, sem tenant). security-mcp
        # é gateway-only: a execução real entra pelo sidecar HTTP (/mcp/tools/call), onde
        # o tenant vem dos claims verificados. Aqui recusamos fail-closed (sem tenant).
        if name not in _TOOL_SCHEMAS:
            payload: dict[str, Any] = {"error": "unknown_tool", "tool": name}
        else:
            payload = {
                "error": "tenant_context_required",
                "tool": name,
                "detail": (
                    "security-mcp é tenant-scoped e gateway-only; chame via o sidecar HTTP "
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
