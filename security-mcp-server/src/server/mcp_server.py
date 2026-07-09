"""Security MCP Server — Streamable HTTP (SDK oficial) + auth (padrão da plataforma).

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
from src.tools.security_tools import (
    review_secure_code,
    scan_secrets,
    calculate_cvss,
    generate_threat_model,
    map_attack_surface,
    generate_security_controls,
    scan_dependency_risks,
    analyze_compliance,
    generate_incident_response_plan,
    harden_headers,
    check_password_policy,
    stub_tool,
)

# ── Configuração (env) ──────────────────────────────────────────────────── #
RESOURCE = os.getenv("SECURITY_RESOURCE", "http://localhost:7100/mcp")
AS_ISSUER = os.getenv("AS_ISSUER", "http://localhost:7103")
AS_JWKS_URL = os.getenv("AS_JWKS_URL", f"{AS_ISSUER}/.well-known/jwks.json")
RESOURCE_METADATA_URL = os.getenv(
    "SECURITY_PRM_URL", "http://localhost:7100/.well-known/oauth-protected-resource"
)

# ── Registro de ferramentas: (fn, scope mínimo, sensitive) ─────────────────── #
TOOL_REGISTRY: dict[str, tuple[Callable, str, bool]] = {
    "review_secure_code": (review_secure_code, "security:scan", False),
    "scan_secrets": (scan_secrets, "security:scan", False),
    "scan_dependency_risks": (scan_dependency_risks, "security:scan", False),
    "calculate_cvss": (calculate_cvss, "security:read", False),
    "harden_headers": (harden_headers, "security:read", False),
    "check_password_policy": (check_password_policy, "security:read", False),
    "analyze_compliance": (analyze_compliance, "security:read", False),
    "map_attack_surface": (map_attack_surface, "security:read", False),
    "generate_threat_model": (generate_threat_model, "security:model", False),
    "generate_security_controls": (generate_security_controls, "security:model", False),
    "generate_incident_response_plan": (
        generate_incident_response_plan,
        "security:model",
        False,
    ),
    "status": (stub_tool, "security:read", False),
}

SCOPES_SUPPORTED = ["security:read", "security:scan", "security:model"]


def _scope_for_request(method: str, tool: str | None) -> str | None:
    """Escopo mínimo exigido por request JSON-RPC (least privilege por ferramenta)."""
    if method != "tools/call" or not tool:
        return None  # initialize / tools/list: basta token válido
    entry = TOOL_REGISTRY.get(tool)
    return entry[1] if entry else "security:read"


def build_mcp() -> FastMCP:
    # stateful por padrão (compatível com clientes reais/Desktop); stateless opcional
    # para escala horizontal atrás de LB. MCP_STATELESS=1 força stateless.
    stateless = os.getenv("MCP_STATELESS", "0") == "1"
    from shared.mcp_auth import transport_security_from_env

    mcp = FastMCP(
        name="security-mcp",
        instructions=SYSTEM_PROMPT,
        stateless_http=stateless,
        transport_security=transport_security_from_env(),
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
        gateway_static_validators,
        protected_resource_metadata,
    )

    mcp = build_mcp()

    @mcp.custom_route("/v1/health", methods=["GET"])
    async def health(_req: Request):
        return JSONResponse({"status": "ok", "server": "security-mcp"})

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
        # Hop S2S do gateway (token estático via MCP_GATEWAY_STATIC_TOKEN) + JWKS/OAuth (clientes).
        validators = gateway_static_validators(SCOPES_SUPPORTED) + [
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

    uvicorn.run(build_app(), host="0.0.0.0", port=int(os.getenv("MCP_PORT", "7100")))


if __name__ == "__main__":
    main()
