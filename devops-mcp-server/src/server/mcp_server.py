"""Servidor MCP do devops — sidecar kind=mcp_http, GATEWAY-READY (Model C).

Reescrito para o padrão canônico do platform-service-template (v2.0). Implementa o
contrato de integração com o MCP Gateway central (platform-mcp-gateway):
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

Transporte: stdio (primário, MCP) + sidecar HTTP (:MCP_PORT, default 7100):
  GET  /v1/health        — liveness (health_path do registro, sem token)
  GET  /mcp/tools/list   — catálogo governado (com metadados de policy)
  POST /mcp/tools/call   — execução (inner token obrigatório, exceto _EXEMPT_TOOLS)

NOTA: devops-mcp é compute-only (gera artefatos a partir dos inputs; não há
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
from ..tools.devops_tools import (
    generate_dockerfile,
    generate_github_actions_pipeline,
    generate_helm_chart,
    generate_kubernetes_manifest,
    stub_tool,
)

_log = logging.getLogger(__name__)

# ── Tool Schemas + Policy metadata (STD-MCP-001 CI-2) ─────────────────────────
# Cada tool declara description/schema + os 4 campos de política:
#   capability     — id estável <namespace>.<tool> (não derivar por nome no gateway)
#   required_scope — escopo de execução <namespace>:<resource_type>:<acao> (least-privilege)
#   resource_type  — tipo de recurso tocado
#   data_domain    — domínio de dado (governa HITL floor / classificação LGPD)
# inputSchema MUST ser type=object com properties. Consulta/status/análise são
# :read (não geram artefato novo); geradores são :write.
# ─────────────────────────────────────────────────────────────────────────────
_ARR = {"type": "array"}
_STR_ARR = {"type": "array", "items": {"type": "string"}}
_OBJ = {"type": "object"}
_STR = {"type": "string"}
_INT = {"type": "integer"}


def _schema(props: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "additionalProperties": False, "properties": props}


_TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    # ── Leitura / status (:read) ────────────────────────────────────────────────
    "status": {
        "description": "Status check stub.",
        "capability": "devops-mcp.status",
        "required_scope": "devops-mcp:status:read",
        "resource_type": "status",
        "data_domain": "operational",
        "schema": _schema({}),
    },
    # ── Geração de artefatos / infra (:write) ───────────────────────────────────
    "generate_kubernetes_manifest": {
        "description": "Generate Kubernetes manifests (Deployment, Service, ConfigMap).",
        "capability": "devops-mcp.generate_kubernetes_manifest",
        "required_scope": "devops-mcp:k8s_manifest:write",
        "resource_type": "k8s_manifest",
        "data_domain": "devops",
        "schema": _schema({
            "application": dict(_STR, description="Nome da aplicação."),
            "replicas": dict(_INT, description="Número de réplicas (opcional)."),
        }),
    },
    "generate_dockerfile": {
        "description": "Generate optimized Dockerfile.",
        "capability": "devops-mcp.generate_dockerfile",
        "required_scope": "devops-mcp:dockerfile:write",
        "resource_type": "dockerfile",
        "data_domain": "devops",
        "schema": _schema({
            "application": dict(_STR, description="Nome da aplicação."),
            "runtime": dict(_STR, description="Runtime base (ex. python:3.11; opcional)."),
        }),
    },
    "generate_github_actions_pipeline": {
        "description": "Generate GitHub Actions CI/CD pipeline.",
        "capability": "devops-mcp.generate_github_actions_pipeline",
        "required_scope": "devops-mcp:pipeline:write",
        "resource_type": "pipeline",
        "data_domain": "devops",
        "schema": _schema({
            "application": dict(_STR, description="Nome da aplicação."),
        }),
    },
    "generate_helm_chart": {
        "description": "Generate Helm Chart for Kubernetes deployment.",
        "capability": "devops-mcp.generate_helm_chart",
        "required_scope": "devops-mcp:helm_chart:write",
        "resource_type": "helm_chart",
        "data_domain": "devops",
        "schema": _schema({
            "app_name": dict(_STR, description="Nome da aplicação/chart."),
        }),
    },
}

# 'status' é a tool tokenless de liveness (CI-7) — sem inner token.
_EXEMPT_TOOLS: frozenset[str] = frozenset({"status"})
# Denylist fail-safe: tools que retornam segredos NUNCA saem pelo gateway (CI-7).
_EXCLUDE_TOOLS: frozenset[str] = frozenset()

# Campos de policy repassados no /mcp/tools/list (o gateway lê estes campos).
_POLICY_FIELDS = ("capability", "required_scope", "resource_type", "data_domain")


# ── Verificação do inner Twin Token (STD-SEC-006 / CI-4/CI-5) ─────────────────

def _verify_inner_token(twin_token: str, settings: Settings) -> dict[str, Any]:
    """Re-verifica o inner Twin Token na PRÓPRIA audiência (mcp:devops-mcp).

    O gateway já verificou o front token; o devops é 'one more verified client'
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
        algorithms=["RS256"],                         # RS256 exclusivo (STD-SEC-001)
        audience=settings.mcp_twin_audience,          # a falha de integração nº 1
        options={"require": ["exp", "aud", "jti"]},   # sem jti → rejeita (JTI_REQUIRED)
    )


# ── Dispatcher (compute-only: sem client, tenant_id só p/ governança) ─────────

def _dispatch(name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Despacha a chamada para a função de tool. tenant_id é injetado pelo PEP nos
    args (INV-3) mas as tools compute-only não o consomem."""
    if name == "status":
        return stub_tool()
    if name == "generate_kubernetes_manifest":
        return generate_kubernetes_manifest(
            application=args.get("application", "app"), replicas=args.get("replicas", 3)
        )
    if name == "generate_dockerfile":
        return generate_dockerfile(
            application=args.get("application", "app"),
            runtime=args.get("runtime", "python:3.11"),
        )
    if name == "generate_github_actions_pipeline":
        return generate_github_actions_pipeline(application=args.get("application", "app"))
    if name == "generate_helm_chart":
        return generate_helm_chart(app_name=args.get("app_name", "app"))
    raise KeyError(name)


# ── HTTP Sidecar ──────────────────────────────────────────────────────────────

def _build_http_app(settings: Settings) -> FastAPI:
    """Cria o sidecar HTTP (health + bridge governado /mcp/tools/*)."""
    app = FastAPI(
        title="devops-mcp API",
        version="0.1.0",
        docs_url="/docs" if settings.docs_enabled else None,   # false em todo ambiente
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
    _log.info("devops_mcp_ready tools=%d", len(_TOOL_SCHEMAS))

    server: Server = Server("devops-mcp-server")

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
