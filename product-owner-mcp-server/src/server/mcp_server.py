"""Servidor MCP do product-owner — sidecar kind=mcp_http, GATEWAY-READY (Model C).

Reescrito para o padrão canônico do platform-service-template (v2.0). Implementa o
contrato de integração com o MCP Gateway central (platform-mcp-gateway):
  - docs/standards/STD-MCP-001-mcp-gateway-integration-contract.md  (CI-1..CI-11)
  - docs/standards/STD-SEC-006-token-model-c-inner-token.md          (inner token / audiência)

Pontos gateway-ready:
  1. /mcp/tools/list emite, por tool, inputSchema type=object + capability +
     required_scope + resource_type + data_domain (o gateway NÃO deriva por nome).
  2. /mcp/tools/call re-verifica o **inner Twin Token** (aud=mcp:product-owner-mcp) via
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

NOTA: product-owner-mcp é compute-only (gera artefatos a partir dos inputs; não há
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
from ..tools.product_owner_tools import (
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

_log = logging.getLogger(__name__)

# ── Tool Schemas + Policy metadata (STD-MCP-001 CI-2) ─────────────────────────
# Cada tool declara description/schema + os 4 campos de política:
#   capability     — id estável <namespace>.<tool> (não derivar por nome no gateway)
#   required_scope — escopo de execução <namespace>:<resource_type>:<acao> (least-privilege)
#   resource_type  — tipo de recurso tocado
#   data_domain    — domínio de dado (governa HITL floor / classificação LGPD)
# inputSchema MUST ser type=object com properties. Análise/priorização/mapeamento/
# cálculo são :read (não geram artefato novo); geradores são :write.
# ─────────────────────────────────────────────────────────────────────────────
_ARR = {"type": "array"}
_STR_ARR = {"type": "array", "items": {"type": "string"}}
_OBJ = {"type": "object"}
_STR = {"type": "string"}
_NUM = {"type": "number"}


def _schema(props: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "additionalProperties": False, "properties": props}


_TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    # ── Leitura / análise / priorização / cálculo (:read) ──────────────────────
    "analyze_product_problem": {
        "description": "Estrutura a análise de um problema de negócio a partir do enunciado e sintomas.",
        "capability": "product-owner-mcp.analyze_product_problem",
        "required_scope": "product-owner-mcp:problem:read",
        "resource_type": "problem",
        "data_domain": "product-owner",
        "schema": _schema({
            "problem_statement": dict(_STR, description="Enunciado do problema de negócio."),
            "affected_users": dict(_STR_ARR, description="Usuários afetados (opcional)."),
            "symptoms": dict(_STR_ARR, description="Sintomas observados (opcional)."),
            "business_impact": dict(_STR, description="Impacto de negócio (opcional)."),
        }),
    },
    "calculate_rice_score": {
        "description": "Calcula RICE score: (Reach x Impact x Confidence) / Effort.",
        "capability": "product-owner-mcp.calculate_rice_score",
        "required_scope": "product-owner-mcp:rice_score:read",
        "resource_type": "rice_score",
        "data_domain": "product-owner",
        "schema": _schema({
            "reach": dict(_NUM, description="Alcance (pessoas/eventos por período, >= 0)."),
            "impact": dict(_NUM, description="Impacto por usuário (> 0)."),
            "confidence": dict(_NUM, description="Confiança (0-1 fração ou 1-100 percentual)."),
            "effort": dict(_NUM, description="Esforço em pessoa-mês/sprint (> 0)."),
            "feature": dict(_STR, description="Nome da feature avaliada (opcional)."),
        }),
    },
    "prioritize_backlog": {
        "description": "Prioriza itens do backlog e retorna ordenado (desc) com rank.",
        "capability": "product-owner-mcp.prioritize_backlog",
        "required_scope": "product-owner-mcp:backlog:read",
        "resource_type": "backlog",
        "data_domain": "product-owner",
        "schema": _schema({
            "items": dict(_ARR, description="Itens do backlog a priorizar."),
            "framework": dict(_STR, description="Framework de priorização (default RICE)."),
        }),
    },
    "map_product_risks": {
        "description": "Classifica riscos de produto nas 4 categorias de Cagan (valor, usabilidade, viabilidade, feasibility).",
        "capability": "product-owner-mcp.map_product_risks",
        "required_scope": "product-owner-mcp:risks:read",
        "resource_type": "risks",
        "data_domain": "product-owner",
        "schema": _schema({
            "feature": dict(_STR, description="Feature/iniciativa avaliada."),
            "risks": dict(_ARR, description="Riscos {descrição,categoria,...} (opcional)."),
        }),
    },
    "map_user_journey": {
        "description": "Monta a jornada do usuário em stages a partir dos passos fornecidos.",
        "capability": "product-owner-mcp.map_user_journey",
        "required_scope": "product-owner-mcp:user_journey:read",
        "resource_type": "user_journey",
        "data_domain": "product-owner",
        "schema": _schema({
            "persona": dict(_STR, description="Persona da jornada."),
            "steps": dict(_ARR, description="Passos/etapas da jornada."),
            "scenario": dict(_STR, description="Cenário/contexto (opcional)."),
        }),
    },
    "map_user_personas": {
        "description": "Estrutura personas de usuário a partir dos inputs.",
        "capability": "product-owner-mcp.map_user_personas",
        "required_scope": "product-owner-mcp:user_personas:read",
        "resource_type": "user_personas",
        "data_domain": "product-owner",
        "schema": _schema({
            "personas": dict(_ARR, description="Personas {nome,objetivos,dores,...}."),
        }),
    },
    "generate_discovery_questions": {
        "description": "Gera perguntas de discovery/validação a partir da hipótese e das incógnitas.",
        "capability": "product-owner-mcp.generate_discovery_questions",
        "required_scope": "product-owner-mcp:discovery:read",
        "resource_type": "discovery",
        "data_domain": "product-owner",
        "schema": _schema({
            "hypothesis": dict(_STR, description="Hipótese a validar."),
            "target_users": dict(_STR_ARR, description="Usuários-alvo (opcional)."),
            "unknowns": dict(_STR_ARR, description="Incógnitas a explorar (opcional)."),
        }),
    },
    # ── Geração de artefatos (:write) ──────────────────────────────────────────
    "define_mvp_scope": {
        "description": "Divide features em must/should/could + out-of-scope para um MVP.",
        "capability": "product-owner-mcp.define_mvp_scope",
        "required_scope": "product-owner-mcp:mvp_scope:write",
        "resource_type": "mvp_scope",
        "data_domain": "product-owner",
        "schema": _schema({
            "product": dict(_STR, description="Nome do produto."),
            "features": dict(_ARR, description="Features candidatas ao MVP."),
            "goal": dict(_STR, description="Objetivo do MVP (opcional)."),
        }),
    },
    "define_product_metrics": {
        "description": "Deriva KPIs e indicadores leading/lagging a partir dos objetivos.",
        "capability": "product-owner-mcp.define_product_metrics",
        "required_scope": "product-owner-mcp:product_metrics:write",
        "resource_type": "product_metrics",
        "data_domain": "product-owner",
        "schema": _schema({
            "product": dict(_STR, description="Nome do produto."),
            "objectives": dict(_STR_ARR, description="Objetivos do produto."),
            "north_star": dict(_STR, description="Métrica North Star (opcional)."),
        }),
    },
    "define_product_vision": {
        "description": "Monta visão/missão/objetivos/critérios de sucesso a partir dos inputs.",
        "capability": "product-owner-mcp.define_product_vision",
        "required_scope": "product-owner-mcp:product_vision:write",
        "resource_type": "product_vision",
        "data_domain": "product-owner",
        "schema": _schema({
            "product": dict(_STR, description="Nome do produto."),
            "target_audience": dict(_STR, description="Público-alvo."),
            "problem": dict(_STR, description="Problema endereçado."),
            "differentiator": dict(_STR, description="Diferencial (opcional)."),
            "goals": dict(_STR_ARR, description="Objetivos (opcional)."),
        }),
    },
    "generate_feature_spec": {
        "description": "Monta a especificação de uma feature a partir dos inputs.",
        "capability": "product-owner-mcp.generate_feature_spec",
        "required_scope": "product-owner-mcp:feature_spec:write",
        "resource_type": "feature_spec",
        "data_domain": "product-owner",
        "schema": _schema({
            "feature": dict(_STR, description="Nome da feature."),
            "problem": dict(_STR, description="Problema resolvido (opcional)."),
            "user_value": dict(_STR, description="Valor para o usuário (opcional)."),
            "requirements": dict(_STR_ARR, description="Requisitos (opcional)."),
            "acceptance_criteria": dict(_STR_ARR, description="Critérios de aceite (opcional)."),
        }),
    },
    "generate_go_to_market_brief": {
        "description": "Monta um brief de Go-To-Market a partir dos inputs.",
        "capability": "product-owner-mcp.generate_go_to_market_brief",
        "required_scope": "product-owner-mcp:gtm_brief:write",
        "resource_type": "gtm_brief",
        "data_domain": "product-owner",
        "schema": _schema({
            "product": dict(_STR, description="Nome do produto."),
            "target_segment": dict(_STR, description="Segmento-alvo."),
            "value_proposition": dict(_STR, description="Proposta de valor."),
            "channels": dict(_STR_ARR, description="Canais de aquisição (opcional)."),
            "launch_date": dict(_STR, description="Data de lançamento (opcional)."),
        }),
    },
    "generate_handoff_to_architecture": {
        "description": "Monta o handoff para Arquitetura a partir dos inputs da feature.",
        "capability": "product-owner-mcp.generate_handoff_to_architecture",
        "required_scope": "product-owner-mcp:handoff_architecture:write",
        "resource_type": "handoff_architecture",
        "data_domain": "product-owner",
        "schema": _schema({
            "feature": dict(_STR, description="Nome da feature."),
            "requirements": dict(_STR_ARR, description="Requisitos (opcional)."),
            "integrations": dict(_STR_ARR, description="Integrações (opcional)."),
            "scale_expectations": dict(_STR, description="Expectativas de escala (opcional)."),
            "constraints": dict(_STR_ARR, description="Restrições (opcional)."),
        }),
    },
    "generate_handoff_to_design": {
        "description": "Monta o handoff para Design a partir dos inputs da feature.",
        "capability": "product-owner-mcp.generate_handoff_to_design",
        "required_scope": "product-owner-mcp:handoff_design:write",
        "resource_type": "handoff_design",
        "data_domain": "product-owner",
        "schema": _schema({
            "feature": dict(_STR, description="Nome da feature."),
            "user_journeys": dict(_STR_ARR, description="Jornadas de usuário (opcional)."),
            "personas": dict(_STR_ARR, description="Personas (opcional)."),
            "key_screens": dict(_STR_ARR, description="Telas-chave (opcional)."),
        }),
    },
    "generate_handoff_to_engineering": {
        "description": "Monta o handoff para Engenharia a partir dos inputs da feature.",
        "capability": "product-owner-mcp.generate_handoff_to_engineering",
        "required_scope": "product-owner-mcp:handoff_engineering:write",
        "resource_type": "handoff_engineering",
        "data_domain": "product-owner",
        "schema": _schema({
            "feature": dict(_STR, description="Nome da feature."),
            "user_stories": dict(_ARR, description="User stories (opcional)."),
            "dependencies": dict(_STR_ARR, description="Dependências (opcional)."),
            "acceptance_criteria": dict(_STR_ARR, description="Critérios de aceite (opcional)."),
        }),
    },
    "generate_release_plan": {
        "description": "Monta um plano de release faseado a partir das features e marcos.",
        "capability": "product-owner-mcp.generate_release_plan",
        "required_scope": "product-owner-mcp:release_plan:write",
        "resource_type": "release_plan",
        "data_domain": "product-owner",
        "schema": _schema({
            "product": dict(_STR, description="Nome do produto."),
            "features": dict(_ARR, description="Features do release."),
            "milestones": dict(_STR_ARR, description="Marcos (opcional)."),
            "target_date": dict(_STR, description="Data-alvo (opcional)."),
        }),
    },
    "generate_user_stories": {
        "description": "Gera user stories bem-formadas + critérios de aceite a partir de uma feature/épico.",
        "capability": "product-owner-mcp.generate_user_stories",
        "required_scope": "product-owner-mcp:user_stories:write",
        "resource_type": "user_stories",
        "data_domain": "product-owner",
        "schema": _schema({
            "feature": dict(_STR, description="Feature/épico."),
            "role": dict(_STR, description="Papel do usuário (opcional)."),
            "roles": dict(_STR_ARR, description="Papéis de usuário (opcional)."),
            "goals": dict(_STR_ARR, description="Objetivos (opcional)."),
            "benefit": dict(_STR, description="Benefício (opcional)."),
        }),
    },
}

# product-owner-mcp não tem tool tokenless; a liveness é o /v1/health (CI-7).
_EXEMPT_TOOLS: frozenset[str] = frozenset()
# Denylist fail-safe: tools que retornam segredos NUNCA saem pelo gateway (CI-7).
_EXCLUDE_TOOLS: frozenset[str] = frozenset()

# Campos de policy repassados no /mcp/tools/list (o gateway lê estes campos).
_POLICY_FIELDS = ("capability", "required_scope", "resource_type", "data_domain")


# ── Verificação do inner Twin Token (STD-SEC-006 / CI-4/CI-5) ─────────────────

def _verify_inner_token(twin_token: str, settings: Settings) -> dict[str, Any]:
    """Re-verifica o inner Twin Token na PRÓPRIA audiência (mcp:product-owner-mcp).

    O gateway já verificou o front token; o product-owner é 'one more verified client'
    (defense in depth). RS256 via JWKS do platform-admin; audiência exata; jti
    obrigatório. Levanta em qualquer falha (fail-closed).
    """
    if not settings.mcp_twin_audience or not settings.url_admin_twin_jwks:
        raise PermissionError(
            "integração com o gateway não configurada: defina MCP_TWIN_AUDIENCE "
            "(mcp:product-owner-mcp) e URL_ADMIN_TWIN_JWKS (ver STD-SEC-006 / IT-006)."
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
    if name == "analyze_product_problem":
        return analyze_product_problem(
            problem_statement=args.get("problem_statement", ""),
            affected_users=args.get("affected_users"),
            symptoms=args.get("symptoms"),
            business_impact=args.get("business_impact"),
        )
    if name == "calculate_rice_score":
        return calculate_rice_score(
            reach=args.get("reach", 0.0), impact=args.get("impact", 0.0),
            confidence=args.get("confidence", 0.0), effort=args.get("effort", 0.0),
            feature=args.get("feature"),
        )
    if name == "prioritize_backlog":
        return prioritize_backlog(
            items=args.get("items", []), framework=args.get("framework", "RICE")
        )
    if name == "map_product_risks":
        return map_product_risks(
            feature=args.get("feature", ""), risks=args.get("risks")
        )
    if name == "map_user_journey":
        return map_user_journey(
            persona=args.get("persona", ""), steps=args.get("steps", []),
            scenario=args.get("scenario"),
        )
    if name == "map_user_personas":
        return map_user_personas(personas=args.get("personas", []))
    if name == "generate_discovery_questions":
        return generate_discovery_questions(
            hypothesis=args.get("hypothesis", ""),
            target_users=args.get("target_users"), unknowns=args.get("unknowns"),
        )
    if name == "define_mvp_scope":
        return define_mvp_scope(
            product=args.get("product", ""), features=args.get("features", []),
            goal=args.get("goal"),
        )
    if name == "define_product_metrics":
        return define_product_metrics(
            product=args.get("product", ""), objectives=args.get("objectives", []),
            north_star=args.get("north_star"),
        )
    if name == "define_product_vision":
        return define_product_vision(
            product=args.get("product", ""), target_audience=args.get("target_audience", ""),
            problem=args.get("problem", ""), differentiator=args.get("differentiator"),
            goals=args.get("goals"),
        )
    if name == "generate_feature_spec":
        return generate_feature_spec(
            feature=args.get("feature", ""), problem=args.get("problem"),
            user_value=args.get("user_value"), requirements=args.get("requirements"),
            acceptance_criteria=args.get("acceptance_criteria"),
        )
    if name == "generate_go_to_market_brief":
        return generate_go_to_market_brief(
            product=args.get("product", ""), target_segment=args.get("target_segment", ""),
            value_proposition=args.get("value_proposition", ""),
            channels=args.get("channels"), launch_date=args.get("launch_date"),
        )
    if name == "generate_handoff_to_architecture":
        return generate_handoff_to_architecture(
            feature=args.get("feature", ""), requirements=args.get("requirements"),
            integrations=args.get("integrations"),
            scale_expectations=args.get("scale_expectations"),
            constraints=args.get("constraints"),
        )
    if name == "generate_handoff_to_design":
        return generate_handoff_to_design(
            feature=args.get("feature", ""), user_journeys=args.get("user_journeys"),
            personas=args.get("personas"), key_screens=args.get("key_screens"),
        )
    if name == "generate_handoff_to_engineering":
        return generate_handoff_to_engineering(
            feature=args.get("feature", ""), user_stories=args.get("user_stories"),
            dependencies=args.get("dependencies"),
            acceptance_criteria=args.get("acceptance_criteria"),
        )
    if name == "generate_release_plan":
        return generate_release_plan(
            product=args.get("product", ""), features=args.get("features", []),
            milestones=args.get("milestones"), target_date=args.get("target_date"),
        )
    if name == "generate_user_stories":
        return generate_user_stories(
            feature=args.get("feature", ""), role=args.get("role"),
            roles=args.get("roles"), goals=args.get("goals"), benefit=args.get("benefit"),
        )
    raise KeyError(name)


# ── HTTP Sidecar ──────────────────────────────────────────────────────────────

def _build_http_app(settings: Settings) -> FastAPI:
    """Cria o sidecar HTTP (health + bridge governado /mcp/tools/*)."""
    app = FastAPI(
        title="product-owner-mcp API",
        version="0.1.0",
        docs_url="/docs" if settings.docs_enabled else None,   # false em todo ambiente
        redoc_url=None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
    )

    @app.get("/v1/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "service": "product-owner-mcp", "tools": len(_TOOL_SCHEMAS)}

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
    _log.info("product_owner_mcp_ready tools=%d", len(_TOOL_SCHEMAS))

    server: Server = Server("product-owner-mcp-server")

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
