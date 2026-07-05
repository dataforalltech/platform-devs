"""Frontend MCP Server — Streamable HTTP (SDK oficial) + auth (padrão da plataforma).

Conforme MCP_SERVICE_STANDARD.md:
- Transporte: Streamable HTTP via FastMCP (conexão nativa do Claude Code, sem wrapper).
- Auth: middleware Bearer valida tokens do auth-mcp (JWKS) e aplica escopo por ferramenta.
- Publica /.well-known/oauth-protected-resource (RFC 9728) para disparar o fluxo OAuth do cliente.
- Health público; qualquer rota /mcp sem token válido responde 401.
"""
from __future__ import annotations

import os
from typing import Callable

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from src.prompts.system_prompt import SYSTEM_PROMPT
from src.tools.frontend_tools import (
    generate_form_with_validation,
    generate_nextjs_page,
    generate_react_component,
    generate_storybook_story,
    stub_tool,
)

# ── Configuração (env) ──────────────────────────────────────────────────── #
RESOURCE = os.getenv("FRONTEND_RESOURCE", "http://localhost:7120/mcp")
AS_ISSUER = os.getenv("AS_ISSUER", "http://localhost:7103")
AS_JWKS_URL = os.getenv("AS_JWKS_URL", f"{AS_ISSUER}/.well-known/jwks.json")
RESOURCE_METADATA_URL = os.getenv(
    "FRONTEND_PRM_URL", "http://localhost:7120/.well-known/oauth-protected-resource"
)

# ── Registro de ferramentas: (fn, scope mínimo, sensitive) ─────────────────── #
# Escopos:
#   frontend:read  → verificação de status / análise (não gera artefatos)
#   frontend:write → geração de componentes, páginas, stories e formulários (UI)
# Nenhuma ferramenta é destrutiva/irreversível, então sensitive=False em todas.
TOOL_REGISTRY: dict[str, tuple[Callable, str, bool]] = {
    # Geração de componentes / UI / páginas
    "generate_react_component": (generate_react_component, "frontend:write", False),
    "generate_nextjs_page": (generate_nextjs_page, "frontend:write", False),
    "generate_storybook_story": (generate_storybook_story, "frontend:write", False),
    "generate_form_with_validation": (generate_form_with_validation, "frontend:write", False),
    # Leitura / status
    "status": (stub_tool, "frontend:read", False),
}

SCOPES_SUPPORTED = ["frontend:read", "frontend:write"]


def _scope_for_request(method: str, tool: str | None) -> str | None:
    """Escopo mínimo exigido por request JSON-RPC (least privilege por ferramenta)."""
    if method != "tools/call" or not tool:
        return None  # initialize / tools/list: basta token válido
    entry = TOOL_REGISTRY.get(tool)
    return entry[1] if entry else "frontend:read"


def build_mcp() -> FastMCP:
    mcp = FastMCP(name="frontend-mcp", instructions=SYSTEM_PROMPT, stateless_http=(os.getenv("MCP_STATELESS", "0") == "1"))
    for name, (fn, _scope, _sensitive) in TOOL_REGISTRY.items():
        mcp.add_tool(fn, name=name)
    return mcp


def build_app(validators: list[Callable] | None = None):
    """Monta o app Streamable HTTP + rotas públicas + middleware de auth.

    `validators` permite injetar validadores no teste; em produção usa JWKS do auth-mcp.
    """
    from shared.mcp_auth import BearerAuthMiddleware, JwtValidator, protected_resource_metadata

    mcp = build_mcp()

    @mcp.custom_route("/v1/health", methods=["GET"])
    async def health(_req: Request):
        return JSONResponse({"status": "ok", "server": "frontend-mcp"})

    @mcp.custom_route("/.well-known/oauth-protected-resource", methods=["GET"])
    async def prm(_req: Request):
        return JSONResponse(protected_resource_metadata(
            resource=RESOURCE,
            authorization_servers=[AS_ISSUER],
            scopes=SCOPES_SUPPORTED,
        ))

    app = mcp.streamable_http_app()

    if validators is None:
        validators = [JwtValidator(issuer=AS_ISSUER, audience=RESOURCE, jwks_url=AS_JWKS_URL).validate]

    return BearerAuthMiddleware(
        app,
        resource_metadata_url=RESOURCE_METADATA_URL,
        validators=validators,
        scope_for_request=_scope_for_request,
    )


def main() -> None:
    import uvicorn
    uvicorn.run(build_app(), host="0.0.0.0", port=int(os.getenv("MCP_PORT", "7120")))


if __name__ == "__main__":
    main()
