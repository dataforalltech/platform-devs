"""Servidor MCP do audit — sidecar kind=mcp_http, GATEWAY-READY (Model C).

Reescrito para o padrão canônico do platform-service-template (v2.0). Implementa o
contrato de integração com o MCP Gateway central (platform-mcp-gateway):
  - docs/standards/STD-MCP-001-mcp-gateway-integration-contract.md  (CI-1..CI-11)
  - docs/standards/STD-SEC-006-token-model-c-inner-token.md          (inner token / audiência)

Pontos gateway-ready:
  1. /mcp/tools/list emite, por tool, inputSchema type=object + capability +
     required_scope + resource_type + data_domain (o gateway NÃO deriva por nome).
  2. /mcp/tools/call re-verifica o **inner Twin Token** (aud=mcp:audit-mcp) via
     JWKS do platform-admin, na PRÓPRIA audiência (defense in depth — CI-4/CI-5). O
     inner token chega em params._meta.twin_token.
  3. tenant_id vem SEMPRE dos claims do token verificado — nunca de argumento do
     cliente (SEC-035 / INV-3). As tools de auditoria não o consomem (é só p/
     governança), então o dispatcher o remove antes de chamar a função.
  4. _EXEMPT_TOOLS (tokenless) e _EXCLUDE_TOOLS (denylist fail-safe).
  5. /docs desabilitado (DOCS_ENABLED=false — HTTP-01).

Transporte: stdio (primário, MCP) + sidecar HTTP (:MCP_PORT, default 7100):
  GET  /v1/health        — liveness (health_path do registro, sem token)
  GET  /mcp/tools/list   — catálogo governado (com metadados de policy)
  POST /mcp/tools/call   — execução (inner token obrigatório, exceto _EXEMPT_TOOLS)

NOTA: audit-mcp persiste no PostgreSQL via ``AuditStore`` (backend real, não
compute-only), então o dispatcher recebe (store, settings) e injeta ambos nas
tools — preservando a lógica original de src/tools/.
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

from ..config.settings import AuditSettings, get_settings
from ..db.store import AuditStore
from ..tools.approval_tool import submit_audit_approval
from ..tools.audit_tool import get_audit_status, run_audit
from ..tools.checklist_tool import get_compliance_checklist
from ..tools.gate_tool import get_audit_gate_result
from ..tools.policy_tool import get_compliance_policy, set_service_criticality
from ..tools.report_tool import get_audit_report, list_audits

_log = logging.getLogger(__name__)

# ── Tool Schemas + Policy metadata (STD-MCP-001 CI-2) ─────────────────────────
# Cada tool declara, além de description/schema, os 4 campos de política:
#   capability     — id estável <namespace>.<tool> (não derivar por nome no gateway)
#   required_scope — escopo de execução no formato dominio:tipo:acao (least-privilege)
#   resource_type  — tipo de recurso tocado
#   data_domain    — domínio de dado (governa HITL floor / classificação LGPD)
# inputSchema MUST ser type=object com properties (senão a validação no front-door
# é fail-open). Mutação → verbo :write; consulta → :read.
# ─────────────────────────────────────────────────────────────────────────────
_TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "run_audit": {
        "description": "Executa auditoria completa de um repo em um ambiente",
        "capability": "audit-mcp.run_audit",
        "required_scope": "audit-mcp:audit:write",
        "resource_type": "audit",
        "data_domain": "compliance",
        "schema": {
            "type": "object",
            "properties": {
                "service": {"type": "string", "description": "Nome do serviço"},
                "repo": {"type": "string", "description": "Nome do repositório"},
                "env": {
                    "type": "string",
                    "description": "Ambiente: dev, hml, prod",
                    "enum": ["dev", "hml", "prod"],
                },
                "repo_path": {
                    "type": "string",
                    "description": "Caminho local do repo (opcional, tenta resolver automaticamente)",
                },
            },
            "required": ["service", "repo", "env"],
        },
    },
    "get_audit_status": {
        "description": "Retorna status da auditoria mais recente de um serviço/ambiente",
        "capability": "audit-mcp.get_audit_status",
        "required_scope": "audit-mcp:audit:read",
        "resource_type": "audit",
        "data_domain": "compliance",
        "schema": {
            "type": "object",
            "properties": {
                "service": {"type": "string", "description": "Nome do serviço"},
                "env": {
                    "type": "string",
                    "description": "Ambiente: dev, hml, prod",
                    "enum": ["dev", "hml", "prod"],
                },
            },
            "required": ["service", "env"],
        },
    },
    "get_compliance_policy": {
        "description": "Retorna política de conformidade para um ambiente",
        "capability": "audit-mcp.get_compliance_policy",
        "required_scope": "audit-mcp:policy:read",
        "resource_type": "policy",
        "data_domain": "compliance",
        "schema": {
            "type": "object",
            "properties": {
                "env": {
                    "type": "string",
                    "description": "Ambiente: dev, hml, prod",
                    "enum": ["dev", "hml", "prod"],
                }
            },
            "required": ["env"],
        },
    },
    "get_compliance_checklist": {
        "description": "Retorna checklist dinâmico para um repo/ambiente (preview sem persistir)",
        "capability": "audit-mcp.get_compliance_checklist",
        "required_scope": "audit-mcp:checklist:read",
        "resource_type": "checklist",
        "data_domain": "compliance",
        "schema": {
            "type": "object",
            "properties": {
                "service": {"type": "string", "description": "Nome do serviço"},
                "repo": {"type": "string", "description": "Nome do repositório"},
                "env": {
                    "type": "string",
                    "description": "Ambiente: dev, hml, prod",
                    "enum": ["dev", "hml", "prod"],
                },
            },
            "required": ["service", "repo", "env"],
        },
    },
    "submit_audit_approval": {
        "description": "Submete aprovação ou rejeição manual de uma auditoria",
        "capability": "audit-mcp.submit_audit_approval",
        "required_scope": "audit-mcp:approval:write",
        "resource_type": "approval",
        "data_domain": "compliance",
        "schema": {
            "type": "object",
            "properties": {
                "audit_id": {"type": "string", "description": "ID da auditoria (audit_...)"},
                "approved_by": {"type": "string", "description": "Identificador de quem aprova"},
                "decision": {
                    "type": "string",
                    "description": "Decisão: approved ou rejected",
                    "enum": ["approved", "rejected"],
                },
                "role": {
                    "type": "string",
                    "description": "Role do aprovador (developer, lead, architect)",
                },
                "notes": {"type": "string", "description": "Notas da aprovação"},
            },
            "required": ["audit_id", "approved_by", "decision"],
        },
    },
    "get_audit_report": {
        "description": "Retorna relatório consolidado de conformidade",
        "capability": "audit-mcp.get_audit_report",
        "required_scope": "audit-mcp:report:read",
        "resource_type": "report",
        "data_domain": "compliance",
        "schema": {
            "type": "object",
            "properties": {
                "service": {"type": "string", "description": "Filtro por serviço (opcional)"},
                "env": {
                    "type": "string",
                    "description": "Filtro por ambiente (opcional)",
                },
                "period_days": {
                    "type": "integer",
                    "description": "Período de relatório em dias (default: 30)",
                },
            },
        },
    },
    "list_audits": {
        "description": "Lista auditorias com filtros opcionais",
        "capability": "audit-mcp.list_audits",
        "required_scope": "audit-mcp:audit:read",
        "resource_type": "audit",
        "data_domain": "compliance",
        "schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "description": "Filtro por status"},
                "env": {"type": "string", "description": "Filtro por ambiente"},
                "service": {"type": "string", "description": "Filtro por serviço"},
                "limit": {
                    "type": "integer",
                    "description": "Limite de resultados (default: 50)",
                },
            },
        },
    },
    "set_service_criticality": {
        "description": "Define nível de criticidade de um serviço",
        "capability": "audit-mcp.set_service_criticality",
        "required_scope": "audit-mcp:criticality:write",
        "resource_type": "criticality",
        "data_domain": "compliance",
        "schema": {
            "type": "object",
            "properties": {
                "service": {"type": "string", "description": "Nome do serviço"},
                "criticality": {
                    "type": "string",
                    "description": "Nível de criticidade",
                    "enum": ["low", "medium", "high", "critical"],
                },
                "updated_by": {"type": "string", "description": "Quem está atualizando"},
            },
            "required": ["service", "criticality", "updated_by"],
        },
    },
    "get_audit_gate_result": {
        "description": "Retorna resultado do gate audit_compliance para integração com pipeline-mcp",
        "capability": "audit-mcp.get_audit_gate_result",
        "required_scope": "audit-mcp:gate:read",
        "resource_type": "gate",
        "data_domain": "compliance",
        "schema": {
            "type": "object",
            "properties": {
                "service": {"type": "string", "description": "Nome do serviço"},
                "env": {
                    "type": "string",
                    "description": "Ambiente: dev, hml, prod",
                    "enum": ["dev", "hml", "prod"],
                },
            },
            "required": ["service", "env"],
        },
    },
}

# Tools encaminhadas SEM inner token (CI-7 exempt_tools — só tokenless). audit-mcp
# não expõe tool pública/tokenless: TODA execução exige inner token válido.
_EXEMPT_TOOLS: frozenset[str] = frozenset()
# Denylist fail-safe: tools que retornam segredos NUNCA saem pelo gateway (CI-7).
_EXCLUDE_TOOLS: frozenset[str] = frozenset()

# Campos de policy repassados no /mcp/tools/list (o gateway lê estes campos).
_POLICY_FIELDS = ("capability", "required_scope", "resource_type", "data_domain")


# ── Verificação do inner Twin Token (STD-SEC-006 / CI-4/CI-5) ─────────────────


def _verify_inner_token(twin_token: str, settings: AuditSettings) -> dict[str, Any]:
    """Re-verifica o inner Twin Token na PRÓPRIA audiência (mcp:audit-mcp).

    O gateway já verificou o front token; o backend é 'one more verified client'
    (defense in depth). RS256 via JWKS do platform-admin; audiência exata; jti
    obrigatório. Levanta em qualquer falha (fail-closed).
    """
    if not settings.mcp_twin_audience or not settings.url_admin_twin_jwks:
        raise PermissionError(
            "integração com o gateway não configurada: defina MCP_TWIN_AUDIENCE "
            "(mcp:audit-mcp) e URL_ADMIN_TWIN_JWKS (ver STD-SEC-006 / IT-006)."
        )
    signing_key = jwt.PyJWKClient(settings.url_admin_twin_jwks).get_signing_key_from_jwt(twin_token)
    return jwt.decode(
        twin_token,
        signing_key.key,
        algorithms=["RS256"],  # RS256 exclusivo (STD-SEC-001)
        audience=settings.mcp_twin_audience,  # a falha de integração nº 1
        options={"require": ["exp", "aud", "jti"]},  # sem jti → rejeita (JTI_REQUIRED)
    )


# ── Dispatcher (backend-backed: store + settings injetados nas tools) ─────────


def _dispatch(name: str, args: dict[str, Any], store: AuditStore, settings: AuditSettings) -> dict[str, Any]:
    """Despacha a chamada para a função de tool, preservando a assinatura
    ``tool(store, settings, **args)``.

    ``tenant_id`` é injetado pelo PEP nos args (INV-3) apenas para governança; as
    tools de auditoria não o consomem, então é removido antes da chamada.
    """
    call_args = {k: v for k, v in args.items() if k != "tenant_id"}
    try:
        if name == "run_audit":
            return run_audit(store, settings, **call_args)
        if name == "get_audit_status":
            return get_audit_status(store, settings, **call_args)
        if name == "get_compliance_policy":
            return get_compliance_policy(store, settings, **call_args)
        if name == "get_compliance_checklist":
            return get_compliance_checklist(store, settings, **call_args)
        if name == "submit_audit_approval":
            return submit_audit_approval(store, settings, **call_args)
        if name == "get_audit_report":
            return get_audit_report(store, settings, **call_args)
        if name == "list_audits":
            return list_audits(store, settings, **call_args)
        if name == "set_service_criticality":
            return set_service_criticality(store, settings, **call_args)
        if name == "get_audit_gate_result":
            return get_audit_gate_result(store, settings, **call_args)
    except TypeError as exc:
        return {"error": "invalid_arguments", "message": str(exc), "tool": name}
    raise KeyError(name)


# ── HTTP Sidecar ──────────────────────────────────────────────────────────────


def _build_http_app(settings: AuditSettings, store: AuditStore) -> FastAPI:
    """Cria o sidecar HTTP (health + bridge governado /mcp/tools/*)."""
    app = FastAPI(
        title="audit-mcp API",
        version="0.1.0",
        docs_url="/docs" if settings.docs_enabled else None,  # false em todo ambiente
        redoc_url=None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
    )

    @app.get("/v1/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "service": "audit-mcp", "tools": len(_TOOL_SCHEMAS)}

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
    def http_call_tool(body: dict) -> Any:
        params = body.get("params", body)
        name = params.get("name", "")
        arguments = dict(params.get("arguments", {}) or {})

        if name in _EXCLUDE_TOOLS:
            return JSONResponse(status_code=403, content={"error": "tool_excluded", "tool": name})

        # Execução (não-exempt) exige inner token válido; tenant vem dos claims.
        if name not in _EXEMPT_TOOLS:
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
            # SEC-035 / INV-3: tenant SEMPRE dos claims, nunca de argumento do cliente.
            arguments["tenant_id"] = tenant_id

        try:
            payload = _dispatch(name, arguments, store, settings)
        except KeyError:
            return JSONResponse(status_code=404, content={"error": "unknown_tool", "tool": name})
        except Exception as exc:  # noqa: BLE001 — a resposta carrega o erro
            _log.exception("tool_internal_error: %s", name)
            payload = {"error": "internal_error", "detail": str(exc), "tool": name}
        content = [TextContent(type="text", text=json.dumps(payload, ensure_ascii=False, indent=2))]
        return {"result": {"content": [c.model_dump(exclude_none=True) for c in content]}}

    return app


# ── Server (stdio + sidecar) ──────────────────────────────────────────────────


def build_server() -> tuple[Any, AuditSettings, AuditStore, FastAPI]:
    """Inicializa o MCP Server (stdio), settings, o store e o sidecar HTTP."""
    settings = get_settings()
    logging.basicConfig(level=settings.log_level, format="%(levelname)s %(name)s %(message)s")
    store = AuditStore(settings=settings)
    http_app = _build_http_app(settings, store)
    _log.info("audit_mcp_ready tools=%d", len(_TOOL_SCHEMAS))

    server: Server = Server("audit-mcp-server")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(name=name, description=meta["description"], inputSchema=meta["schema"])
            for name, meta in _TOOL_SCHEMAS.items()
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any] | None) -> list[TextContent]:
        args = arguments or {}
        try:
            payload = _dispatch(name, args, store, settings)
        except KeyError:
            payload = {"error": "unknown_tool", "tool": name}
        except Exception as exc:  # noqa: BLE001
            payload = {"error": "internal_error", "detail": str(exc), "tool": name}
            _log.exception("tool_internal_error: %s", name)
        return [TextContent(type="text", text=json.dumps(payload, ensure_ascii=False, indent=2))]

    return server, settings, store, http_app


# ── Entry point ───────────────────────────────────────────────────────────────


async def _run() -> None:
    import uvicorn
    from mcp.server.stdio import stdio_server

    server, settings, _store, http_app = build_server()
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

        _server, settings, _store, http_app = build_server()
        uvicorn.run(http_app, host="0.0.0.0", port=settings.mcp_port, log_level="warning")  # noqa: S104
        return
    asyncio.run(_run())


if __name__ == "__main__":
    main()
