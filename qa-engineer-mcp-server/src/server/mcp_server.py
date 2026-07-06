"""QA-Engineer MCP Server — Streamable HTTP (SDK oficial) + auth (padrão da plataforma).

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
from src.tools.qa_engineer_tools import (
    analyze_quality_requirement,
    classify_bug_severity,
    generate_api_tests,
    generate_bug_report,
    generate_cypress_tests,
    generate_e2e_tests,
    generate_gherkin_scenarios,
    generate_k6_performance_test,
    generate_playwright_tests,
    generate_postman_collection,
    generate_quality_gate,
    generate_regression_suite,
    generate_smoke_test_suite,
    generate_test_cases,
    generate_test_plan,
    generate_uat_checklist,
    generate_unit_tests,
    review_test_coverage,
    validate_story_testability,
)

# ── Configuração (env) ──────────────────────────────────────────────────── #
RESOURCE = os.getenv("QA_ENGINEER_RESOURCE", "http://localhost:7124/mcp")
AS_ISSUER = os.getenv("AS_ISSUER", "http://localhost:7103")
AS_JWKS_URL = os.getenv("AS_JWKS_URL", f"{AS_ISSUER}/.well-known/jwks.json")
RESOURCE_METADATA_URL = os.getenv(
    "QA_ENGINEER_PRM_URL", "http://localhost:7124/.well-known/oauth-protected-resource"
)

# ── Registro de ferramentas: (fn, scope mínimo, sensitive) ─────────────────── #
# Escopos:
#   qa-engineer:read  → análise, classificação, validação, revisão e geração de
#                       artefatos (todas as ferramentas apenas sintetizam texto/dict,
#                       sem mutação de estado — logo, leitura por least-privilege)
#   qa-engineer:write → reservado para futuras ferramentas que persistam estado
# Nenhuma ferramenta é destrutiva/irreversível, então sensitive=False em todas.
TOOL_REGISTRY: dict[str, tuple[Callable, str, bool]] = {
    # Leitura / análise
    "analyze_quality_requirement": (
        analyze_quality_requirement,
        "qa-engineer:read",
        False,
    ),
    "classify_bug_severity": (classify_bug_severity, "qa-engineer:read", False),
    "validate_story_testability": (
        validate_story_testability,
        "qa-engineer:read",
        False,
    ),
    "review_test_coverage": (review_test_coverage, "qa-engineer:read", False),
    # Geração de artefatos / testes (read-only: só sintetizam texto/dict)
    "generate_test_plan": (generate_test_plan, "qa-engineer:read", False),
    "generate_test_cases": (generate_test_cases, "qa-engineer:read", False),
    "generate_gherkin_scenarios": (
        generate_gherkin_scenarios,
        "qa-engineer:read",
        False,
    ),
    "generate_e2e_tests": (generate_e2e_tests, "qa-engineer:read", False),
    "generate_api_tests": (generate_api_tests, "qa-engineer:read", False),
    "generate_unit_tests": (generate_unit_tests, "qa-engineer:read", False),
    "generate_playwright_tests": (generate_playwright_tests, "qa-engineer:read", False),
    "generate_cypress_tests": (generate_cypress_tests, "qa-engineer:read", False),
    "generate_postman_collection": (
        generate_postman_collection,
        "qa-engineer:read",
        False,
    ),
    "generate_bug_report": (generate_bug_report, "qa-engineer:read", False),
    "generate_quality_gate": (generate_quality_gate, "qa-engineer:read", False),
    "generate_uat_checklist": (generate_uat_checklist, "qa-engineer:read", False),
    "generate_k6_performance_test": (
        generate_k6_performance_test,
        "qa-engineer:read",
        False,
    ),
    "generate_regression_suite": (generate_regression_suite, "qa-engineer:read", False),
    "generate_smoke_test_suite": (generate_smoke_test_suite, "qa-engineer:read", False),
}

SCOPES_SUPPORTED = ["qa-engineer:read", "qa-engineer:write"]


def _scope_for_request(method: str, tool: str | None) -> str | None:
    """Escopo mínimo exigido por request JSON-RPC (least privilege por ferramenta)."""
    if method != "tools/call" or not tool:
        return None  # initialize / tools/list: basta token válido
    entry = TOOL_REGISTRY.get(tool)
    return entry[1] if entry else "qa-engineer:read"


def build_mcp() -> FastMCP:
    mcp = FastMCP(
        name="qa-engineer-mcp",
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
        return JSONResponse({"status": "ok", "server": "qa-engineer-mcp"})

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

    uvicorn.run(build_app(), host="0.0.0.0", port=int(os.getenv("MCP_PORT", "7124")))


if __name__ == "__main__":
    main()
