"""Product-Owner MCP Server — Streamable HTTP (SDK oficial) + auth (padrão da plataforma).

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
from src.tools.product_owner_tools import (
    analyze_product_problem,
    calculate_rice_score,
    define_mvp_scope,
    define_product_metrics,
    define_product_vision,
    generate_discovery_questions,
    generate_feature_spec,
    generate_go_to_market_brief,
    generate_handoff_to_architecture,
    generate_handoff_to_design,
    generate_handoff_to_engineering,
    generate_release_plan,
    generate_user_stories,
    map_product_risks,
    map_user_journey,
    map_user_personas,
    prioritize_backlog,
)

# ── Configuração (env) ──────────────────────────────────────────────────── #
RESOURCE = os.getenv("PRODUCT_OWNER_RESOURCE", "http://localhost:7122/mcp")
AS_ISSUER = os.getenv("AS_ISSUER", "http://localhost:7103")
AS_JWKS_URL = os.getenv("AS_JWKS_URL", f"{AS_ISSUER}/.well-known/jwks.json")
RESOURCE_METADATA_URL = os.getenv(
    "PRODUCT_OWNER_PRM_URL",
    "http://localhost:7122/.well-known/oauth-protected-resource",
)

# ── Registro de ferramentas: (fn, scope mínimo, sensitive) ─────────────────── #
# Escopos:
#   product-owner:read  → análise, priorização, mapeamento e cálculo (ex.: RICE); não gera artefatos
#   product-owner:write → geração de artefatos (histórias, backlog, roadmap, specs, planos, handoffs)
# Nenhuma ferramenta é destrutiva/irreversível, então sensitive=False em todas.
TOOL_REGISTRY: dict[str, tuple[Callable, str, bool]] = {
    # Leitura / análise / priorização / cálculo
    "analyze_product_problem": (analyze_product_problem, "product-owner:read", False),
    "calculate_rice_score": (calculate_rice_score, "product-owner:read", False),
    "prioritize_backlog": (prioritize_backlog, "product-owner:read", False),
    "map_product_risks": (map_product_risks, "product-owner:read", False),
    "map_user_journey": (map_user_journey, "product-owner:read", False),
    "map_user_personas": (map_user_personas, "product-owner:read", False),
    "generate_discovery_questions": (
        generate_discovery_questions,
        "product-owner:read",
        False,
    ),
    # Geração de artefatos
    "define_mvp_scope": (define_mvp_scope, "product-owner:write", False),
    "define_product_metrics": (define_product_metrics, "product-owner:write", False),
    "define_product_vision": (define_product_vision, "product-owner:write", False),
    "generate_feature_spec": (generate_feature_spec, "product-owner:write", False),
    "generate_go_to_market_brief": (
        generate_go_to_market_brief,
        "product-owner:write",
        False,
    ),
    "generate_handoff_to_architecture": (
        generate_handoff_to_architecture,
        "product-owner:write",
        False,
    ),
    "generate_handoff_to_design": (
        generate_handoff_to_design,
        "product-owner:write",
        False,
    ),
    "generate_handoff_to_engineering": (
        generate_handoff_to_engineering,
        "product-owner:write",
        False,
    ),
    "generate_release_plan": (generate_release_plan, "product-owner:write", False),
    "generate_user_stories": (generate_user_stories, "product-owner:write", False),
}

SCOPES_SUPPORTED = ["product-owner:read", "product-owner:write"]


def _scope_for_request(method: str, tool: str | None) -> str | None:
    """Escopo mínimo exigido por request JSON-RPC (least privilege por ferramenta)."""
    if method != "tools/call" or not tool:
        return None  # initialize / tools/list: basta token válido
    entry = TOOL_REGISTRY.get(tool)
    return entry[1] if entry else "product-owner:read"


def build_mcp() -> FastMCP:
    mcp = FastMCP(
        name="product-owner-mcp",
        instructions=SYSTEM_PROMPT,
        stateless_http=(os.getenv("MCP_STATELESS", "0") == "1"),
    )
    for name, (fn, _scope, _sensitive) in TOOL_REGISTRY.items():
        mcp.add_tool(fn, name=name)
    return mcp


def build_app(validators: list[Callable] | None = None):
    """Monta o app Streamable HTTP + rotas públicas + middleware de auth.

    `validators` permite injetar validadores no teste; em produção usa JWKS do auth-mcp.
    """
    from shared.mcp_auth import (
        BearerAuthMiddleware,
        JwtValidator,
        protected_resource_metadata,
    )

    mcp = build_mcp()

    @mcp.custom_route("/v1/health", methods=["GET"])
    async def health(_req: Request):
        return JSONResponse({"status": "ok", "server": "product-owner-mcp"})

    @mcp.custom_route("/.well-known/oauth-protected-resource", methods=["GET"])
    async def prm(_req: Request):
        return JSONResponse(
            protected_resource_metadata(
                resource=RESOURCE,
                authorization_servers=[AS_ISSUER],
                scopes=SCOPES_SUPPORTED,
            )
        )

    app = mcp.streamable_http_app()

    if validators is None:
        validators = [
            JwtValidator(
                issuer=AS_ISSUER, audience=RESOURCE, jwks_url=AS_JWKS_URL
            ).validate
        ]

    return BearerAuthMiddleware(
        app,
        resource_metadata_url=RESOURCE_METADATA_URL,
        validators=validators,
        scope_for_request=_scope_for_request,
    )


def main() -> None:
    import uvicorn

    uvicorn.run(build_app(), host="0.0.0.0", port=int(os.getenv("MCP_PORT", "7122")))


if __name__ == "__main__":
    main()
