"""Servidor MCP Dev-Twin — 9 tools de autenticação, contexto e administração.

Tools:
  Auth (5):  authenticate, whoami, get_twin_context, refresh_context, context_status
  Admin (4): register_token, revoke_token, rotate_token, list_tokens

authenticate é a PRIMEIRA tool chamada em toda sessão de agente.
Valida o token do usuário, carrega perfil e captura contexto de ambiente.

Transporte: Streamable HTTP em :7101 (gateway e cross-MCP consultam via HTTP).
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from fastapi import FastAPI
from mcp.server import Server
from mcp.types import TextContent, Tool

from ..api.router import make_router
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

_TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    # ── Auth ──────────────────────────────────────────────────────────────── #
    "authenticate": {
        "description": (
            "PRIMEIRA tool por sessão. "
            "Valida TWIN_TOKEN, carrega perfil (nome, role, escopos, ambiente). "
            "Sem authenticate(), whoami() e get_twin_context() falham."
        ),
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
        "schema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    "get_twin_context": {
        "description": (
            "Contexto completo da sessão: identidade, git/OS/hostname e MCPs disponíveis. "
            "Coleta lazy na primeira chamada (cache 60s)."
        ),
        "schema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    "refresh_context": {
        "description": (
            "Recaptura contexto de ambiente (git branch, cwd) sem invalidar autenticação. "
            "Use após trocar de branch ou diretório."
        ),
        "schema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    "context_status": {
        "description": (
            "Retorna métricas de uso do contexto Claude: tool_calls desde autenticação, "
            "tempo decorrido e recomendação de /compact (ok | compact_soon | compact_now). "
            "Use periodicamente para saber quando compactar o contexto e reduzir custo de tokens."
        ),
        "schema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    # ── Admin ─────────────────────────────────────────────────────────────── #
    "register_token": {
        "description": (
            "Admin — Registra usuário e emite token de acesso (exibido uma única vez). "
            "Requer TWIN_ADMIN_TOKEN. Roles: developer | admin | agent | readonly."
        ),
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
            "Admin — Lista metadados de usuários/tokens (sem exibir valores). "
            "Requer TWIN_ADMIN_TOKEN."
        ),
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


# Escopo mínimo por ferramenta (least privilege). write = ação/mutação; read = consulta.
# Tools admin (register/revoke/rotate) mutam tokens de acesso → sensíveis, exigem twin:write.
SCOPE_FOR_TOOL: dict[str, str] = {
    # ── Auth ── #
    "authenticate": "twin:write",  # muta estado de sessão (autentica) → sensível
    "whoami": "twin:read",
    "get_twin_context": "twin:read",
    "refresh_context": "twin:write",  # recaptura/atualiza contexto da sessão
    "context_status": "twin:read",
    # ── Admin (sensíveis: gerenciam tokens de acesso) ── #
    "register_token": "twin:write",
    "revoke_token": "twin:write",
    "rotate_token": "twin:write",
    "list_tokens": "twin:read",
}
SCOPES_SUPPORTED = ["twin:read", "twin:write"]


def _build_http_app(settings: DevTwinSettings) -> FastAPI:
    app = FastAPI(title="dev-twin-mcp API", version="0.1.0", docs_url="/docs")
    router = make_router(settings.api_token)
    app.include_router(router)
    return app


def build_server() -> tuple[Any, TokenStore, DevTwinSettings, FastAPI]:
    settings = get_settings()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

    store = TokenStore(settings)
    http_app = _build_http_app(settings)

    _log.info("dev_twin_mcp_ready pg_host=%s pg_db=%s", settings.pg_host, settings.pg_db)

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
        _log.info("tool_called: %s", name)
        try:
            SessionManager.increment_tool_calls()
            payload = _dispatch(name, args, store, settings)
        except KeyError:
            payload = {"error": "unknown_tool", "tool": name}
            _log.error("unknown_tool: %s", name)
        except Exception as exc:  # noqa: BLE001
            payload = {"error": "internal_error", "details": str(exc), "tool": name}
            _log.exception("tool_internal_error: %s", name)
        return [TextContent(type="text", text=json.dumps(payload, ensure_ascii=False, indent=2))]

    @http_app.get("/mcp/tools/list")
    async def http_list_tools() -> dict:
        tools = await list_tools()
        return {"result": {"tools": [t.model_dump(exclude_none=True) for t in tools]}}

    @http_app.post("/mcp/tools/call")
    async def http_call_tool(body: dict) -> dict:
        params = body.get("params", body)
        result = await call_tool(params.get("name", ""), params.get("arguments", {}))
        return {"result": {"content": [r.model_dump(exclude_none=True) for r in result]}}

    return server, store, settings, http_app


def _dispatch(
    name: str,
    args: dict[str, Any],
    store: TokenStore,
    settings: DevTwinSettings,
) -> dict:
    if name == "authenticate":
        return authenticate(store, token=args["token"])
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
            store,
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
            store,
            admin_token_configured=settings.admin_token,
            admin_token=args["admin_token"],
            identifier=args["identifier"],
        )
    if name == "rotate_token":
        return rotate_token(
            store,
            admin_token_configured=settings.admin_token,
            admin_token=args["admin_token"],
            identifier=args["identifier"],
        )
    if name == "list_tokens":
        return list_tokens(
            store,
            admin_token_configured=settings.admin_token,
            admin_token=args["admin_token"],
            include_revoked=args.get("include_revoked", False),
        )
    raise KeyError(name)


def build_app(validators: Any = None):
    """Monta o app Streamable HTTP + auth (padrão da plataforma) sobre o Server legado.

    Preserva build_server() (Server de baixo nível + dispatch com store/settings);
    só troca o transporte para Streamable HTTP e adiciona o BearerAuthMiddleware
    com escopo por ferramenta (least privilege).
    """
    from shared.mcp_auth import mount_lowlevel_streamable_http

    server, _store, _settings, _http = build_server()
    return mount_lowlevel_streamable_http(
        server,
        resource=os.getenv("TWIN_RESOURCE", "http://localhost:7101/mcp"),
        prm_url=os.getenv(
            "TWIN_PRM_URL",
            "http://localhost:7101/.well-known/oauth-protected-resource",
        ),
        as_issuer=os.getenv("AS_ISSUER", "http://localhost:7103"),
        as_jwks_url=os.getenv("AS_JWKS_URL", "http://localhost:7103/.well-known/jwks.json"),
        scopes_supported=SCOPES_SUPPORTED,
        scope_for_tool=SCOPE_FOR_TOOL,
        validators=validators,
    )


def main() -> None:
    """Entry point — Streamable HTTP + auth."""
    import uvicorn

    uvicorn.run(build_app(), host="0.0.0.0", port=int(os.getenv("MCP_PORT", "7101")))


if __name__ == "__main__":
    main()
