"""Architecture MCP Server — Streamable HTTP (SDK oficial) + auth (padrão da plataforma).

Conforme MCP_SERVICE_STANDARD.md:
- Transporte: Streamable HTTP via FastMCP (conexão nativa do Claude Code, sem wrapper).
- Auth: middleware Bearer valida tokens do auth-mcp (JWKS) e aplica escopo por ferramenta.
- Publica /.well-known/oauth-protected-resource (RFC 9728) para disparar o fluxo OAuth do cliente.
- Health público; qualquer rota /mcp sem token válido responde 401.
"""

from __future__ import annotations

import os
from typing import Any, Callable

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from src.prompts.system_prompt import SYSTEM_PROMPT
from src.tools.architecture_tools import (
    generate_solution_blueprint,
    generate_c4_diagram,
    generate_architecture,
    status,
)

# ── Configuração (env) ──────────────────────────────────────────────────── #
RESOURCE = os.getenv("ARCHITECTURE_RESOURCE", "http://localhost:7118/mcp")
AS_ISSUER = os.getenv("AS_ISSUER", "http://localhost:7103")
AS_JWKS_URL = os.getenv("AS_JWKS_URL", f"{AS_ISSUER}/.well-known/jwks.json")
RESOURCE_METADATA_URL = os.getenv(
    "ARCHITECTURE_PRM_URL", "http://localhost:7118/.well-known/oauth-protected-resource"
)

# ── Registro de ferramentas: (fn, scope mínimo, sensitive) ─────────────────── #
# Escopos:
#   architecture:read  → verificação de status / leitura (não gera artefatos)
#   architecture:write → geração de blueprints, diagramas C4 e designs de arquitetura
# Nenhuma ferramenta é destrutiva/irreversível, então sensitive=False em todas.
TOOL_REGISTRY: dict[str, tuple[Callable, str, bool]] = {
    # Geração de artefatos de arquitetura
    "generate_solution_blueprint": (
        generate_solution_blueprint,
        "architecture:write",
        False,
    ),
    "generate_c4_diagram": (generate_c4_diagram, "architecture:write", False),
    "generate_architecture": (generate_architecture, "architecture:write", False),
    # Leitura / status
    "status": (status, "architecture:read", False),
}

SCOPES_SUPPORTED = ["architecture:read", "architecture:write"]

# ── JSON input schemas (fonte de verdade documentada) ──────────────────────── #
# O FastMCP deriva o inputSchema real de cada tool a partir das anotações de tipo
# da função (ver build_mcp/list_tools). Este dicionário documenta o contrato
# esperado — os campos e os obrigatórios — e é validado contra os schemas
# derivados em _assert_schema_contract() no build, garantindo que assinatura e
# contrato não divirjam. Cada tool recebe parâmetros (antes recebiam nenhum).
TOOL_INPUT_SCHEMAS: dict[str, dict[str, Any]] = {
    "generate_c4_diagram": {
        "type": "object",
        "properties": {
            "system_name": {
                "type": "string",
                "description": "Nome do software system em foco",
            },
            "actors": {
                "type": "array",
                "description": "Pessoas/sistemas externos (str ou {name,type,description})",
                "items": {"type": ["string", "object"]},
            },
            "containers": {
                "type": "array",
                "description": "Aplicações/serviços internos (str ou {name,technology,description})",
                "items": {"type": ["string", "object"]},
            },
            "relationships": {
                "type": "array",
                "description": "Arestas {source,target,description,technology} ou 'A -> B'",
                "items": {"type": ["string", "object"]},
            },
        },
        "required": [],
    },
    "generate_solution_blueprint": {
        "type": "object",
        "properties": {
            "requirements": {
                "type": "string",
                "description": "Requisitos funcionais/de negócio (texto livre)",
            },
            "solution_name": {"type": "string", "description": "Nome da solução"},
            "context": {
                "type": "string",
                "description": "Contexto adicional (domínio, org)",
            },
            "constraints": {
                "type": "array",
                "description": "Restrições técnicas/organizacionais",
                "items": {"type": "string"},
            },
        },
        "required": [],
    },
    "generate_architecture": {
        "type": "object",
        "properties": {
            "domain": {"type": "string", "description": "Domínio/negócio-alvo"},
            "constraints": {
                "type": "array",
                "description": "Restrições técnicas/organizacionais",
                "items": {"type": "string"},
            },
            "quality_attributes": {
                "type": "array",
                "description": "Atributos de qualidade priorizados",
                "items": {"type": "string"},
            },
            "architecture_name": {
                "type": "string",
                "description": "Nome opcional; default derivado do domínio",
            },
        },
        "required": [],
    },
    "status": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}


async def assert_schema_contract(mcp: FastMCP) -> None:
    """Garante que os schemas derivados pelo FastMCP cobrem o contrato documentado.

    Falha se uma assinatura de tool divergir de TOOL_INPUT_SCHEMAS — ex.: uma
    propriedade documentada some da função. Chamada pelos testes; async porque
    FastMCP.list_tools é async.
    """
    derived: dict[str, set[str]] = {}
    for tool in await mcp.list_tools():
        props = (tool.inputSchema or {}).get("properties", {})
        derived[tool.name] = set(props.keys())
    for name, contract in TOOL_INPUT_SCHEMAS.items():
        expected = set(contract.get("properties", {}).keys())
        actual = derived.get(name, set())
        missing = expected - actual
        if missing:
            raise RuntimeError(
                f"Tool '{name}' perdeu propriedades do contrato documentado: {sorted(missing)}"
            )


def _scope_for_request(method: str, tool: str | None) -> str | None:
    """Escopo mínimo exigido por request JSON-RPC (least privilege por ferramenta)."""
    if method != "tools/call" or not tool:
        return None  # initialize / tools/list: basta token válido
    entry = TOOL_REGISTRY.get(tool)
    return entry[1] if entry else "architecture:read"


def build_mcp() -> FastMCP:
    mcp = FastMCP(
        name="architecture-mcp",
        instructions=SYSTEM_PROMPT,
        stateless_http=(os.getenv("MCP_STATELESS", "0") == "1"),
    )
    for name, (fn, _scope, _sensitive) in TOOL_REGISTRY.items():
        # O inputSchema é derivado das anotações de tipo de cada fn (ver
        # TOOL_INPUT_SCHEMAS para o contrato documentado). Antes as tools não
        # recebiam argumentos; agora expõem parâmetros tipados.
        mcp.add_tool(
            fn,
            name=name,
            description=(fn.__doc__ or "").strip().split("\n", 1)[0] or None,
        )
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
        return JSONResponse({"status": "ok", "server": "architecture-mcp"})

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

    uvicorn.run(build_app(), host="0.0.0.0", port=int(os.getenv("MCP_PORT", "7118")))


if __name__ == "__main__":
    main()
