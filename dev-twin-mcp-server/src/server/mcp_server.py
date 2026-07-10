"""Servidor MCP do dev-twin — sidecar kind=mcp_http, GATEWAY-READY (Model C).

Reescrito para o padrão canônico do platform-service-template (v2.0). Implementa o
contrato de integração com o MCP Gateway central (platform-mcp-gateway):
  - docs/standards/STD-MCP-001-mcp-gateway-integration-contract.md  (CI-1..CI-11)
  - docs/standards/STD-SEC-006-token-model-c-inner-token.md          (inner token / audiência)

Pontos gateway-ready:
  1. /mcp/tools/list emite, por tool, inputSchema type=object + capability +
     required_scope + resource_type + data_domain (o gateway NÃO deriva por nome).
  2. /mcp/tools/call re-verifica o **inner Twin Token** (aud=mcp:dev-twin-mcp) via
     JWKS do platform-admin, na PRÓPRIA audiência (defense in depth — CI-4/CI-5). O
     inner token chega em params._meta.twin_token.
  3. tenant_id vem SEMPRE dos claims do token verificado — nunca de argumento do
     cliente (SEC-035 / INV-3).
  4. _EXEMPT_TOOLS (health/status, sem token) e _EXCLUDE_TOOLS (denylist fail-safe:
     register_token/rotate_token retornam token em plaintext → NUNCA saem pelo gateway).
  5. /docs desabilitado (DOCS_ENABLED=false — HTTP-01).

Transporte: stdio (primário, MCP) + sidecar HTTP (:MCP_PORT, default 7100):
  GET  /v1/health        — liveness (health_path do registro, sem token)
  GET  /mcp/tools/list   — catálogo governado (com metadados de policy)
  POST /mcp/tools/call   — execução (inner token obrigatório, exceto _EXEMPT_TOOLS)

NOTA: dev-twin-mcp é **stateful** (gerencia a tabela agent_tokens em PostgreSQL via
TokenStore). O store é criado de forma lazy (primeira tool que o usa), então o boot
e o /v1/health não dependem do banco.
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

from ..config.settings import DevTwinSettings, get_settings
from ..db.token_store import TokenStore
from ..knowledge.session import SessionManager
from ..tools import (
    authenticate,
    context_status,
    get_twin_context,
    list_tokens,
    refresh_context,
    register_token,
    revoke_token,
    rotate_token,
    whoami,
)

_log = logging.getLogger(__name__)

# ── Tool Schemas + Policy metadata (STD-MCP-001 CI-2) ─────────────────────────
# Cada tool declara, além de description/schema, os 4 campos de política:
#   capability     — id estável <namespace>.<tool> (não derivar por nome no gateway)
#   required_scope — escopo de execução no formato dominio:tipo:acao (least-privilege)
#   resource_type  — tipo de recurso tocado
#   data_domain    — domínio de dado (governa HITL floor / classificação LGPD)
# inputSchema MUST ser type=object com properties (senão a validação no front-door
# é fail-open). Leituras usam verbo :read; mutações usam :write.
# ─────────────────────────────────────────────────────────────────────────────
_TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    # ── Operacional ───────────────────────────────────────────────────────── #
    "status": {
        "description": "Retorna o status real do servidor (nome, versão, nº de tools).",
        "capability": "dev-twin-mcp.status",
        "required_scope": "dev-twin-mcp:status:read",
        "resource_type": "status",
        "data_domain": "operational",
        "schema": {"type": "object", "additionalProperties": False, "properties": {}},
    },
    # ── Auth / sessão ─────────────────────────────────────────────────────── #
    "authenticate": {
        "description": (
            "PRIMEIRA tool por sessão. "
            "Valida TWIN_TOKEN, carrega perfil (nome, role, escopos, ambiente). "
            "Sem authenticate(), whoami() e get_twin_context() falham."
        ),
        "capability": "dev-twin-mcp.authenticate",
        "required_scope": "dev-twin-mcp:session:write",
        "resource_type": "session",
        "data_domain": "identity",
        "schema": {
            "type": "object",
            "properties": {
                "token": {
                    "type": "string",
                    "description": "Token do usuário/agente (TWIN_TOKEN do ambiente).",
                },
            },
            "required": ["token"],
            "additionalProperties": False,
        },
    },
    "whoami": {
        "description": (
            "Retorna o usuário autenticado na sessão: "
            "user_id, name, email, role, scopes, environment, authenticated_at. "
            "Requer authenticate() anterior."
        ),
        "capability": "dev-twin-mcp.whoami",
        "required_scope": "dev-twin-mcp:session:read",
        "resource_type": "session",
        "data_domain": "identity",
        "schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    "get_twin_context": {
        "description": (
            "Contexto completo da sessão: identidade, git/OS/hostname e MCPs disponíveis. "
            "Coleta lazy na primeira chamada (cache 60s)."
        ),
        "capability": "dev-twin-mcp.get_twin_context",
        "required_scope": "dev-twin-mcp:context:read",
        "resource_type": "context",
        "data_domain": "identity",
        "schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    "refresh_context": {
        "description": (
            "Recaptura contexto de ambiente (git branch, cwd) sem invalidar autenticação. "
            "Use após trocar de branch ou diretório."
        ),
        "capability": "dev-twin-mcp.refresh_context",
        "required_scope": "dev-twin-mcp:context:write",
        "resource_type": "context",
        "data_domain": "identity",
        "schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    "context_status": {
        "description": (
            "Retorna métricas de uso do contexto Claude: tool_calls desde autenticação, "
            "tempo decorrido e recomendação de /compact (ok | compact_soon | compact_now). "
            "Use periodicamente para saber quando compactar o contexto e reduzir custo de tokens."
        ),
        "capability": "dev-twin-mcp.context_status",
        "required_scope": "dev-twin-mcp:context:read",
        "resource_type": "context",
        "data_domain": "operational",
        "schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    # ── Admin (gerenciam tokens de acesso) ────────────────────────────────── #
    "register_token": {
        "description": (
            "Admin — Registra usuário e emite token de acesso (exibido uma única vez). "
            "Requer TWIN_ADMIN_TOKEN. Roles: developer | admin | agent | readonly."
        ),
        "capability": "dev-twin-mcp.register_token",
        "required_scope": "dev-twin-mcp:token:write",
        "resource_type": "token",
        "data_domain": "identity",
        "schema": {
            "type": "object",
            "properties": {
                "admin_token": {
                    "type": "string",
                    "description": "Token de admin (TWIN_ADMIN_TOKEN).",
                },
                "name": {"type": "string", "description": "Nome de exibição."},
                "email": {"type": "string", "description": "Email do usuário."},
                "role": {
                    "type": "string",
                    "enum": ["developer", "admin", "agent", "readonly"],
                    "description": "Papel do usuário. Default: developer.",
                    "default": "developer",
                },
                "environment": {
                    "type": "string",
                    "enum": ["dev", "staging", "production"],
                    "description": "Ambiente de atuação. Default: dev.",
                    "default": "dev",
                },
                "scopes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Escopos permitidos. Default: ['*'] (tudo).",
                },
                "expires_in_days": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Validade em dias. Omitir = sem expiração.",
                },
                "tenant_id": {
                    "type": "string",
                    "description": (
                        "Tenant padrão do usuário. Ex: 'tenant_abc123'. "
                        "Quando definido, o config-mcp usa get_session_tenant_config "
                        "para retornar a config deste tenant automaticamente."
                    ),
                },
            },
            "required": ["admin_token", "name", "email"],
            "additionalProperties": False,
        },
    },
    "revoke_token": {
        "description": (
            "Admin — Revoga um token ou todos os tokens de um user_id. "
            "Requer admin_token. O usuário perde acesso imediatamente."
        ),
        "capability": "dev-twin-mcp.revoke_token",
        "required_scope": "dev-twin-mcp:token:write",
        "resource_type": "token",
        "data_domain": "identity",
        "schema": {
            "type": "object",
            "properties": {
                "admin_token": {"type": "string"},
                "identifier": {
                    "type": "string",
                    "description": "Token completo ou user_id a revogar.",
                },
            },
            "required": ["admin_token", "identifier"],
            "additionalProperties": False,
        },
    },
    "rotate_token": {
        "description": (
            "Admin — Revoga o token atual e emite um novo para o mesmo usuário. "
            "Útil para rotação periódica de segurança. "
            "O novo token é exibido uma única vez."
        ),
        "capability": "dev-twin-mcp.rotate_token",
        "required_scope": "dev-twin-mcp:token:write",
        "resource_type": "token",
        "data_domain": "identity",
        "schema": {
            "type": "object",
            "properties": {
                "admin_token": {"type": "string"},
                "identifier": {
                    "type": "string",
                    "description": "Token ou user_id a rotacionar.",
                },
            },
            "required": ["admin_token", "identifier"],
            "additionalProperties": False,
        },
    },
    "list_tokens": {
        "description": (
            "Admin — Lista metadados de usuários/tokens (sem exibir valores). Requer TWIN_ADMIN_TOKEN."
        ),
        "capability": "dev-twin-mcp.list_tokens",
        "required_scope": "dev-twin-mcp:token:read",
        "resource_type": "token",
        "data_domain": "identity",
        "schema": {
            "type": "object",
            "properties": {
                "admin_token": {"type": "string"},
                "include_revoked": {
                    "type": "boolean",
                    "description": "Incluir tokens revogados. Default: false.",
                    "default": False,
                },
            },
            "required": ["admin_token"],
            "additionalProperties": False,
        },
    },
}

# Health/status são encaminhadas SEM inner token (CI-7 exempt_tools — só tokenless).
_EXEMPT_TOOLS: frozenset[str] = frozenset({"status"})
# Denylist fail-safe (CI-7): tools que retornam segredo (token em plaintext) NUNCA
# saem pelo gateway. register_token/rotate_token emitem um bearer token novo → provisão
# de tokens é uma operação de bootstrap out-of-band, não pela porta da frente da IA.
_EXCLUDE_TOOLS: frozenset[str] = frozenset({"register_token", "rotate_token"})

# Campos de policy repassados no /mcp/tools/list (o gateway lê estes campos).
_POLICY_FIELDS = ("capability", "required_scope", "resource_type", "data_domain")


# ── Persistência (lazy) ───────────────────────────────────────────────────────
# O TokenStore abre um pool psycopg2 no __init__; criá-lo de forma lazy mantém o boot
# e o /v1/health resilientes a indisponibilidade momentânea do banco.
_store: TokenStore | None = None


def _get_store(settings: DevTwinSettings) -> TokenStore:
    global _store
    if _store is None:
        _store = TokenStore(settings)
    return _store


# ── Verificação do inner Twin Token (STD-SEC-006 / CI-4/CI-5) ─────────────────


def _verify_inner_token(twin_token: str, settings: DevTwinSettings) -> dict[str, Any]:
    """Re-verifica o inner Twin Token na PRÓPRIA audiência (mcp:dev-twin-mcp).

    O gateway já verificou o front token; o backend é 'one more verified client'
    (defense in depth). RS256 via JWKS do platform-admin; audiência exata; jti
    obrigatório. Levanta em qualquer falha (fail-closed).
    """
    if not settings.mcp_twin_audience or not settings.url_admin_twin_jwks:
        raise PermissionError(
            "integração com o gateway não configurada: defina MCP_TWIN_AUDIENCE "
            "(mcp:dev-twin-mcp) e URL_ADMIN_TWIN_JWKS (ver STD-SEC-006 / IT-006)."
        )
    signing_key = jwt.PyJWKClient(settings.url_admin_twin_jwks).get_signing_key_from_jwt(twin_token)
    return jwt.decode(
        twin_token,
        signing_key.key,
        algorithms=["RS256"],  # RS256 exclusivo (STD-SEC-001)
        audience=settings.mcp_twin_audience,  # a falha de integração nº 1
        options={"require": ["exp", "aud", "jti"]},  # sem jti → rejeita (JTI_REQUIRED)
    )


# ── status (tool operacional, tokenless) ──────────────────────────────────────


def status() -> dict[str, Any]:
    """Retorna o status real do servidor."""
    return {"status": "ok", "service": "dev-twin-mcp", "tools": len(_TOOL_SCHEMAS)}


# ── Dispatcher ────────────────────────────────────────────────────────────────


def _dispatch(name: str, args: dict[str, Any], settings: DevTwinSettings) -> dict[str, Any]:
    """Despacha a chamada para a função de tool. tenant_id é injetado pelo PEP nos
    args (INV-3); as tools de sessão/admin não o consomem (lêem apenas suas chaves)."""
    if name == "status":
        return status()
    if name == "authenticate":
        return authenticate(_get_store(settings), token=args["token"])
    if name == "whoami":
        return whoami()
    if name == "get_twin_context":
        return get_twin_context()
    if name == "refresh_context":
        return refresh_context()
    if name == "context_status":
        return context_status()
    if name == "register_token":
        return register_token(
            _get_store(settings),
            admin_token_configured=settings.admin_token,
            admin_token=args["admin_token"],
            name=args["name"],
            email=args["email"],
            role=args.get("role", "developer"),
            environment=args.get("environment", "dev"),
            scopes=args.get("scopes"),
            expires_in_days=args.get("expires_in_days"),
            tenant_id=args.get("tenant_id"),
        )
    if name == "revoke_token":
        return revoke_token(
            _get_store(settings),
            admin_token_configured=settings.admin_token,
            admin_token=args["admin_token"],
            identifier=args["identifier"],
        )
    if name == "rotate_token":
        return rotate_token(
            _get_store(settings),
            admin_token_configured=settings.admin_token,
            admin_token=args["admin_token"],
            identifier=args["identifier"],
        )
    if name == "list_tokens":
        return list_tokens(
            _get_store(settings),
            admin_token_configured=settings.admin_token,
            admin_token=args["admin_token"],
            include_revoked=args.get("include_revoked", False),
        )
    raise KeyError(name)


# ── HTTP Sidecar ──────────────────────────────────────────────────────────────


def _build_http_app(settings: DevTwinSettings) -> FastAPI:
    """Cria o sidecar HTTP (health + bridge governado /mcp/tools/*)."""
    app = FastAPI(
        title="dev-twin-mcp API",
        version="0.1.0",
        docs_url="/docs" if settings.docs_enabled else None,  # false em todo ambiente
        redoc_url=None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
    )

    @app.get("/v1/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "service": "dev-twin-mcp", "tools": len(_TOOL_SCHEMAS)}

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

        SessionManager.increment_tool_calls()
        try:
            payload = _dispatch(name, arguments, settings)
        except KeyError:
            return JSONResponse(status_code=404, content={"error": "unknown_tool", "tool": name})
        except Exception as exc:  # noqa: BLE001 — a resposta carrega o erro
            _log.exception("tool_internal_error: %s", name)
            payload = {"error": "internal_error", "detail": str(exc), "tool": name}
        content = [TextContent(type="text", text=json.dumps(payload, ensure_ascii=False, indent=2))]
        return {"result": {"content": [c.model_dump(exclude_none=True) for c in content]}}

    return app


# ── Server (stdio + sidecar) ──────────────────────────────────────────────────


def build_server() -> tuple[Any, DevTwinSettings, FastAPI]:
    """Inicializa o MCP Server (stdio), settings e o sidecar HTTP."""
    settings = get_settings()
    logging.basicConfig(level=settings.log_level, format="%(levelname)s %(name)s %(message)s")
    http_app = _build_http_app(settings)
    _log.info("dev_twin_mcp_ready tools=%d", len(_TOOL_SCHEMAS))

    server: Server = Server("dev-twin-mcp-server")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(name=name, description=meta["description"], inputSchema=meta["schema"])
            for name, meta in _TOOL_SCHEMAS.items()
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any] | None) -> list[TextContent]:
        args = arguments or {}
        SessionManager.increment_tool_calls()
        try:
            payload = _dispatch(name, args, settings)
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
