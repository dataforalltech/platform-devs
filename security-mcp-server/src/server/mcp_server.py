"""Servidor MCP do security — sidecar kind=mcp_http, GATEWAY-READY (Model C).

Reescrito para o padrão canônico do platform-service-template (v2.0). Implementa o
contrato de integração com o MCP Gateway central (platform-mcp-gateway):
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

NOTA: security-mcp é compute-only (analisa/gera artefatos a partir dos inputs; não há
backend REST), por isso não há ServiceApiClient — as tools são chamadas diretamente.
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

from ..config.settings import Settings, get_settings
from ..tools.security_tools import (
    analyze_compliance,
    calculate_cvss,
    check_password_policy,
    generate_incident_response_plan,
    generate_security_controls,
    generate_threat_model,
    harden_headers,
    map_attack_surface,
    review_secure_code,
    scan_dependency_risks,
    scan_secrets,
    stub_tool,
)

_log = logging.getLogger(__name__)

# ── Tool Schemas + Policy metadata (STD-MCP-001 CI-2) ─────────────────────────
# Cada tool declara description/schema + os 4 campos de política:
#   capability     — id estável <namespace>.<tool> (não derivar por nome no gateway)
#   required_scope — escopo de execução <namespace>:<resource_type>:<acao> (least-privilege)
#   resource_type  — tipo de recurso tocado
#   data_domain    — domínio de dado (governa HITL floor / classificação LGPD)
# inputSchema MUST ser type=object com properties. Análise/revisão/scan são
# :read (não geram artefato novo); geradores (threat model, controles, IR plan) são :write.
# ─────────────────────────────────────────────────────────────────────────────
_ARR = {"type": "array"}
_STR_ARR = {"type": "array", "items": {"type": "string"}}
_OBJ = {"type": "object"}
_STR = {"type": "string"}


def _schema(props: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "additionalProperties": False, "properties": props}


_TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    # ── Leitura / análise / scan (:read) ───────────────────────────────────────
    "review_secure_code": {
        "description": "Revisa um trecho de código contra padrões OWASP/CWE, com números de linha.",
        "capability": "security-mcp.review_secure_code",
        "required_scope": "security-mcp:code:read",
        "resource_type": "code",
        "data_domain": "security",
        "schema": _schema(
            {
                "code": dict(_STR, description="Código a revisar."),
                "language": dict(_STR, description="Linguagem (python/typescript/...)."),
            }
        ),
    },
    "scan_secrets": {
        "description": "Detecta segredos hardcoded em texto/código. Sempre mascara o valor.",
        "capability": "security-mcp.scan_secrets",
        "required_scope": "security-mcp:secrets:read",
        "resource_type": "secrets",
        "data_domain": "security",
        "schema": _schema(
            {
                "content": dict(_STR, description="Conteúdo/texto a varrer."),
                "filename": dict(_STR, description="Nome do arquivo de origem (opcional)."),
            }
        ),
    },
    "scan_dependency_risks": {
        "description": "Extrai dependências de um manifest e sinaliza riscos heurísticos.",
        "capability": "security-mcp.scan_dependency_risks",
        "required_scope": "security-mcp:dependency:read",
        "resource_type": "dependency",
        "data_domain": "security",
        "schema": _schema(
            {
                "manifest": dict(_STR, description="Conteúdo do manifest de dependências."),
                "ecosystem": dict(_STR, description="Ecossistema (python/npm/...)."),
            }
        ),
    },
    "calculate_cvss": {
        "description": "Calcula CVSS v3.1 base score a partir de um vetor.",
        "capability": "security-mcp.calculate_cvss",
        "required_scope": "security-mcp:cvss:read",
        "resource_type": "cvss",
        "data_domain": "security",
        "schema": _schema(
            {
                "vector": dict(_STR, description="Vetor CVSS 3.1 (ex: CVSS:3.1/AV:N/AC:L/...)."),
            }
        ),
    },
    "harden_headers": {
        "description": "Analisa headers HTTP atuais e recomenda hardening (OWASP Secure Headers).",
        "capability": "security-mcp.harden_headers",
        "required_scope": "security-mcp:headers:read",
        "resource_type": "headers",
        "data_domain": "security",
        "schema": _schema(
            {
                "current_headers": dict(_OBJ, description="Headers HTTP atuais (opcional)."),
            }
        ),
    },
    "check_password_policy": {
        "description": "Avalia uma política de senha contra NIST SP 800-63B.",
        "capability": "security-mcp.check_password_policy",
        "required_scope": "security-mcp:password_policy:read",
        "resource_type": "password_policy",
        "data_domain": "security",
        "schema": _schema(
            {
                "policy": dict(_OBJ, description="Política de senha a avaliar (opcional)."),
            }
        ),
    },
    "analyze_compliance": {
        "description": "Avalia conformidade contra um framework. `context` marca controles atendidos.",
        "capability": "security-mcp.analyze_compliance",
        "required_scope": "security-mcp:compliance:read",
        "resource_type": "compliance",
        "data_domain": "security",
        "schema": _schema(
            {
                "framework": dict(_STR, description="Framework (owasp/lgpd/soc2/iso27001/pci-dss)."),
                "context": dict(_OBJ, description="Contexto com controles atendidos (opcional)."),
            }
        ),
    },
    "map_attack_surface": {
        "description": "Mapeia a superfície de ataque; aceita endpoints/integrações reais.",
        "capability": "security-mcp.map_attack_surface",
        "required_scope": "security-mcp:attack_surface:read",
        "resource_type": "attack_surface",
        "data_domain": "security",
        "schema": _schema(
            {
                "system": dict(_STR, description="Nome do sistema."),
                "endpoints": dict(_ARR, description="Endpoints expostos (opcional)."),
                "integrations": dict(_ARR, description="Integrações (opcional)."),
            }
        ),
    },
    # ── Geração de artefatos (:write) ──────────────────────────────────────────
    "generate_threat_model": {
        "description": "Gera modelo de ameaças STRIDE. Se `components` for informado, mapeia por componente.",
        "capability": "security-mcp.generate_threat_model",
        "required_scope": "security-mcp:threat_model:write",
        "resource_type": "threat_model",
        "data_domain": "security",
        "schema": _schema(
            {
                "system": dict(_STR, description="Nome do sistema."),
                "scope": dict(_STR, description="Escopo da avaliação (opcional)."),
                "components": dict(_ARR, description="Componentes do sistema (opcional)."),
            }
        ),
    },
    "generate_security_controls": {
        "description": "Gera controles técnicos e processuais, mapeados por categoria de ameaça.",
        "capability": "security-mcp.generate_security_controls",
        "required_scope": "security-mcp:security_controls:write",
        "resource_type": "security_controls",
        "data_domain": "security",
        "schema": _schema(
            {
                "system": dict(_STR, description="Nome do sistema."),
                "threat_categories": dict(_ARR, description="Categorias de ameaça/controle (opcional)."),
            }
        ),
    },
    "generate_incident_response_plan": {
        "description": "Gera um runbook de resposta a incidentes seguindo o ciclo NIST SP 800-61.",
        "capability": "security-mcp.generate_incident_response_plan",
        "required_scope": "security-mcp:incident_response:write",
        "resource_type": "incident_response",
        "data_domain": "operational",
        "schema": _schema(
            {
                "incident_type": dict(_STR, description="Tipo de incidente (data_breach/...)."),
                "severity": dict(_STR, description="Severidade (critical/high/medium/low)."),
            }
        ),
    },
    # ── Liveness tokenless (_EXEMPT_TOOLS) ─────────────────────────────────────
    "status": {
        "description": "Status check.",
        "capability": "security-mcp.status",
        "required_scope": "security-mcp:status:read",
        "resource_type": "status",
        "data_domain": "operational",
        "schema": _schema({}),
    },
}

# security-mcp expõe a tool tokenless 'status' (liveness leve); o /v1/health também
# é público (CI-7).
_EXEMPT_TOOLS: frozenset[str] = frozenset({"status"})
# Denylist fail-safe: tools que retornam segredos NUNCA saem pelo gateway (CI-7).
_EXCLUDE_TOOLS: frozenset[str] = frozenset()

# Campos de policy repassados no /mcp/tools/list (o gateway lê estes campos).
_POLICY_FIELDS = ("capability", "required_scope", "resource_type", "data_domain")


# ── Verificação do inner Twin Token (STD-SEC-006 / CI-4/CI-5) ─────────────────


def _verify_inner_token(twin_token: str, settings: Settings) -> dict[str, Any]:
    """Re-verifica o inner Twin Token na PRÓPRIA audiência (mcp:security-mcp).

    O gateway já verificou o front token; o security é 'one more verified client'
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


# ── Dispatcher (compute-only: sem client, tenant_id só p/ governança) ─────────


def _dispatch(name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Despacha a chamada para a função de tool. tenant_id é injetado pelo PEP nos
    args (INV-3) mas as tools compute-only não o consomem."""
    if name == "review_secure_code":
        return review_secure_code(code=args.get("code", ""), language=args.get("language", "python"))
    if name == "scan_secrets":
        return scan_secrets(content=args.get("content", ""), filename=args.get("filename", ""))
    if name == "scan_dependency_risks":
        return scan_dependency_risks(
            manifest=args.get("manifest", ""), ecosystem=args.get("ecosystem", "python")
        )
    if name == "calculate_cvss":
        return calculate_cvss(vector=args.get("vector", ""))
    if name == "harden_headers":
        return harden_headers(current_headers=args.get("current_headers"))
    if name == "check_password_policy":
        return check_password_policy(policy=args.get("policy"))
    if name == "analyze_compliance":
        return analyze_compliance(framework=args.get("framework", "owasp"), context=args.get("context"))
    if name == "map_attack_surface":
        return map_attack_surface(
            system=args.get("system", "system"),
            endpoints=args.get("endpoints"),
            integrations=args.get("integrations"),
        )
    if name == "generate_threat_model":
        return generate_threat_model(
            system=args.get("system", "system"),
            scope=args.get("scope", ""),
            components=args.get("components"),
        )
    if name == "generate_security_controls":
        return generate_security_controls(
            system=args.get("system", "system"),
            threat_categories=args.get("threat_categories"),
        )
    if name == "generate_incident_response_plan":
        return generate_incident_response_plan(
            incident_type=args.get("incident_type", "data_breach"),
            severity=args.get("severity", "high"),
        )
    if name == "status":
        return stub_tool()
    raise KeyError(name)


# ── HTTP Sidecar ──────────────────────────────────────────────────────────────


def _build_http_app(settings: Settings) -> FastAPI:
    """Cria o sidecar HTTP (health + bridge governado /mcp/tools/*)."""
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
            payload = _dispatch(name, arguments)
        except KeyError:
            return JSONResponse(status_code=404, content={"error": "unknown_tool", "tool": name})
        except Exception as exc:  # noqa: BLE001 — a resposta carrega o erro
            _log.exception("tool_internal_error: %s", name)
            payload = {"error": "internal_error", "detail": str(exc), "tool": name}
        content = [TextContent(type="text", text=json.dumps(payload, ensure_ascii=False, indent=2))]
        return {"result": {"content": [c.model_dump(exclude_none=True) for c in content]}}

    return app


# ── Server (stdio + sidecar) ──────────────────────────────────────────────────


def build_server() -> tuple[Any, Settings, FastAPI]:
    """Inicializa o MCP Server (stdio), settings e o sidecar HTTP."""
    settings = get_settings()
    logging.basicConfig(level=settings.log_level, format="%(levelname)s %(name)s %(message)s")
    http_app = _build_http_app(settings)
    _log.info("security_mcp_ready tools=%d", len(_TOOL_SCHEMAS))

    server: Server = Server("security-mcp-server")

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
            payload = _dispatch(name, args)
        except KeyError:
            payload = {"error": "unknown_tool", "tool": name}
        except Exception as exc:  # noqa: BLE001
            payload = {"error": "internal_error", "detail": str(exc), "tool": name}
            _log.exception("tool_internal_error: %s", name)
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
