"""Servidor MCP do qa-engineer — sidecar kind=mcp_http, GATEWAY-READY (Model C).

Reescrito para o padrão canônico do platform-service-template (v2.0). Implementa o
contrato de integração com o MCP Gateway central (platform-mcp-gateway):
  - docs/standards/STD-MCP-001-mcp-gateway-integration-contract.md  (CI-1..CI-11)
  - docs/standards/STD-SEC-006-token-model-c-inner-token.md          (inner token / audiência)

Pontos gateway-ready:
  1. /mcp/tools/list emite, por tool, inputSchema type=object + capability +
     required_scope + resource_type + data_domain (o gateway NÃO deriva por nome).
  2. /mcp/tools/call re-verifica o **inner Twin Token** (aud=mcp:qa-engineer-mcp) via
     JWKS do platform-admin, na PRÓPRIA audiência (defense in depth — CI-4/CI-5). O
     inner token chega em params._meta.twin_token.
  3. tenant_id vem SEMPRE dos claims do token verificado — nunca de argumento do
     cliente (SEC-035 / INV-3).
  4. _EXEMPT_TOOLS (tokenless) e _EXCLUDE_TOOLS (denylist fail-safe).
  5. /docs desabilitado (DOCS_ENABLED=false — HTTP-01).

Transporte: stdio (primário, MCP) + sidecar HTTP (:MCP_PORT, default 7124):
  GET  /v1/health        — liveness (health_path do registro, sem token)
  GET  /mcp/tools/list   — catálogo governado (com metadados de policy)
  POST /mcp/tools/call   — execução (inner token obrigatório, exceto _EXEMPT_TOOLS)

NOTA: qa-engineer-mcp é compute-only (gera artefatos de teste/QA a partir dos
inputs; não há backend REST), por isso não há ServiceApiClient — as tools são
chamadas diretamente.
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
from ..tools.qa_engineer_tools import (
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

_log = logging.getLogger(__name__)

# ── Tool Schemas + Policy metadata (STD-MCP-001 CI-2) ─────────────────────────
# Cada tool declara description/schema + os 4 campos de política:
#   capability     — id estável <namespace>.<tool> (não derivar por nome no gateway)
#   required_scope — escopo de execução <namespace>:<resource_type>:<acao> (least-privilege)
#   resource_type  — tipo de recurso tocado
#   data_domain    — domínio de dado (governa HITL floor / classificação LGPD)
# inputSchema MUST ser type=object com properties. Análise/revisão/validação/
# classificação são :read (não geram artefato novo); geradores são :write.
# ─────────────────────────────────────────────────────────────────────────────
_ARR = {"type": "array"}
_STR_ARR = {"type": "array", "items": {"type": "string"}}
_OBJ = {"type": "object"}
_STR = {"type": "string"}
_INT = {"type": "integer"}
_NUM = {"type": "number"}


def _schema(props: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "additionalProperties": False, "properties": props}


_TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    # ── Leitura / análise / revisão / validação (:read) ────────────────────────
    "analyze_quality_requirement": {
        "description": "Analisa requisito de qualidade: dimensões, riscos, tipos de teste e critérios.",
        "capability": "qa-engineer-mcp.analyze_quality_requirement",
        "required_scope": "qa-engineer-mcp:requirement:read",
        "resource_type": "requirement",
        "data_domain": "qa-engineer",
        "schema": _schema({
            "requirement": dict(_STR, description="Requisito de qualidade a analisar."),
            "context": dict(_OBJ, description="Contexto adicional (opcional)."),
        }),
    },
    "classify_bug_severity": {
        "description": "Classifica severidade de bug (P1–P4) por impacto e frequência, com SLA.",
        "capability": "qa-engineer-mcp.classify_bug_severity",
        "required_scope": "qa-engineer-mcp:bug_severity:read",
        "resource_type": "bug_severity",
        "data_domain": "operational",
        "schema": _schema({
            "description": dict(_STR, description="Descrição do bug."),
            "impact": dict(_STR, description="Impacto (critical/high/medium/low)."),
            "frequency": dict(_STR, description="Frequência (always/often/sometimes/rarely)."),
        }),
    },
    "validate_story_testability": {
        "description": "Valida a testabilidade de uma user story e seus critérios de aceite.",
        "capability": "qa-engineer-mcp.validate_story_testability",
        "required_scope": "qa-engineer-mcp:story:read",
        "resource_type": "story",
        "data_domain": "qa-engineer",
        "schema": _schema({
            "story": dict(_STR, description="User story a validar."),
            "acceptance_criteria": dict(_STR_ARR, description="Critérios de aceite (opcional)."),
        }),
    },
    "review_test_coverage": {
        "description": "Revisa a cobertura de testes de um módulo e aponta gaps e recomendações.",
        "capability": "qa-engineer-mcp.review_test_coverage",
        "required_scope": "qa-engineer-mcp:test_coverage:read",
        "resource_type": "test_coverage",
        "data_domain": "qa-engineer",
        "schema": _schema({
            "module": dict(_STR, description="Módulo avaliado."),
            "current_coverage": dict(_NUM, description="Cobertura atual em % (opcional)."),
        }),
    },
    # ── Geração de artefatos / testes (:write) ─────────────────────────────────
    "generate_test_plan": {
        "description": "Gera plano de teste com objetivos, níveis, ambientes e cronograma.",
        "capability": "qa-engineer-mcp.generate_test_plan",
        "required_scope": "qa-engineer-mcp:test_plan:write",
        "resource_type": "test_plan",
        "data_domain": "qa-engineer",
        "schema": _schema({
            "feature": dict(_STR, description="Funcionalidade alvo."),
            "scope": dict(_STR, description="Escopo (full/partial; opcional)."),
            "team": dict(_STR, description="Time responsável (opcional)."),
        }),
    },
    "generate_test_cases": {
        "description": "Gera casos de teste estruturados para uma funcionalidade.",
        "capability": "qa-engineer-mcp.generate_test_cases",
        "required_scope": "qa-engineer-mcp:test_case:write",
        "resource_type": "test_case",
        "data_domain": "qa-engineer",
        "schema": _schema({
            "feature": dict(_STR, description="Funcionalidade alvo."),
            "test_type": dict(_STR, description="Tipo de teste (functional/...; opcional)."),
            "count": dict(_INT, description="Quantidade de casos (opcional)."),
        }),
    },
    "generate_gherkin_scenarios": {
        "description": "Gera cenários Gherkin (BDD) para uma funcionalidade.",
        "capability": "qa-engineer-mcp.generate_gherkin_scenarios",
        "required_scope": "qa-engineer-mcp:gherkin:write",
        "resource_type": "gherkin",
        "data_domain": "qa-engineer",
        "schema": _schema({
            "feature": dict(_STR, description="Funcionalidade alvo."),
            "scenarios": dict(_STR_ARR, description="Cenários a converter (opcional)."),
        }),
    },
    "generate_e2e_tests": {
        "description": "Gera testes end-to-end (Playwright/Cypress) para uma funcionalidade.",
        "capability": "qa-engineer-mcp.generate_e2e_tests",
        "required_scope": "qa-engineer-mcp:e2e_test:write",
        "resource_type": "e2e_test",
        "data_domain": "qa-engineer",
        "schema": _schema({
            "feature": dict(_STR, description="Funcionalidade alvo."),
            "framework": dict(_STR, description="Framework (playwright/cypress; opcional)."),
            "base_url": dict(_STR, description="URL base da app (opcional)."),
        }),
    },
    "generate_api_tests": {
        "description": "Gera testes de API (pytest+httpx) para um endpoint.",
        "capability": "qa-engineer-mcp.generate_api_tests",
        "required_scope": "qa-engineer-mcp:api_test:write",
        "resource_type": "api_test",
        "data_domain": "qa-engineer",
        "schema": _schema({
            "endpoint": dict(_STR, description="Path do endpoint."),
            "method": dict(_STR, description="Método HTTP (opcional)."),
            "base_url": dict(_STR, description="URL base da API (opcional)."),
        }),
    },
    "generate_unit_tests": {
        "description": "Gera testes unitários (pytest/vitest) para um módulo.",
        "capability": "qa-engineer-mcp.generate_unit_tests",
        "required_scope": "qa-engineer-mcp:unit_test:write",
        "resource_type": "unit_test",
        "data_domain": "qa-engineer",
        "schema": _schema({
            "module": dict(_STR, description="Módulo alvo."),
            "language": dict(_STR, description="Linguagem (python/typescript; opcional)."),
        }),
    },
    "generate_playwright_tests": {
        "description": "Gera testes E2E em Playwright para uma funcionalidade.",
        "capability": "qa-engineer-mcp.generate_playwright_tests",
        "required_scope": "qa-engineer-mcp:playwright_test:write",
        "resource_type": "playwright_test",
        "data_domain": "qa-engineer",
        "schema": _schema({
            "feature": dict(_STR, description="Funcionalidade alvo."),
            "base_url": dict(_STR, description="URL base da app (opcional)."),
        }),
    },
    "generate_cypress_tests": {
        "description": "Gera testes E2E em Cypress para uma funcionalidade.",
        "capability": "qa-engineer-mcp.generate_cypress_tests",
        "required_scope": "qa-engineer-mcp:cypress_test:write",
        "resource_type": "cypress_test",
        "data_domain": "qa-engineer",
        "schema": _schema({
            "feature": dict(_STR, description="Funcionalidade alvo."),
            "base_url": dict(_STR, description="URL base da app (opcional)."),
        }),
    },
    "generate_postman_collection": {
        "description": "Gera coleção Postman com requests e testes para uma API.",
        "capability": "qa-engineer-mcp.generate_postman_collection",
        "required_scope": "qa-engineer-mcp:postman_collection:write",
        "resource_type": "postman_collection",
        "data_domain": "qa-engineer",
        "schema": _schema({
            "api_name": dict(_STR, description="Nome da API/coleção."),
            "base_url": dict(_STR, description="URL base da API (opcional)."),
            "endpoints": dict(_STR_ARR, description="Endpoints (opcional)."),
        }),
    },
    "generate_bug_report": {
        "description": "Gera relatório de bug estruturado com passos e severidade.",
        "capability": "qa-engineer-mcp.generate_bug_report",
        "required_scope": "qa-engineer-mcp:bug_report:write",
        "resource_type": "bug_report",
        "data_domain": "operational",
        "schema": _schema({
            "title": dict(_STR, description="Título do bug."),
            "steps": dict(_STR_ARR, description="Passos para reproduzir (opcional)."),
            "severity": dict(_STR, description="Severidade (P1–P4; opcional)."),
        }),
    },
    "generate_quality_gate": {
        "description": "Gera quality gate de CI com thresholds e config bloqueante.",
        "capability": "qa-engineer-mcp.generate_quality_gate",
        "required_scope": "qa-engineer-mcp:quality_gate:write",
        "resource_type": "quality_gate",
        "data_domain": "operational",
        "schema": _schema({
            "service": dict(_STR, description="Serviço alvo."),
            "thresholds": dict(_OBJ, description="Thresholds do gate (opcional)."),
        }),
    },
    "generate_uat_checklist": {
        "description": "Gera checklist de UAT com itens e stakeholders.",
        "capability": "qa-engineer-mcp.generate_uat_checklist",
        "required_scope": "qa-engineer-mcp:uat_checklist:write",
        "resource_type": "uat_checklist",
        "data_domain": "qa-engineer",
        "schema": _schema({
            "feature": dict(_STR, description="Funcionalidade alvo."),
            "stakeholders": dict(_STR_ARR, description="Stakeholders (opcional)."),
        }),
    },
    "generate_k6_performance_test": {
        "description": "Gera teste de performance k6 para um endpoint.",
        "capability": "qa-engineer-mcp.generate_k6_performance_test",
        "required_scope": "qa-engineer-mcp:performance_test:write",
        "resource_type": "performance_test",
        "data_domain": "operational",
        "schema": _schema({
            "endpoint": dict(_STR, description="Endpoint alvo (URL)."),
            "vus": dict(_INT, description="Usuários virtuais (opcional)."),
            "duration": dict(_STR, description="Duração do teste (ex. 30s; opcional)."),
        }),
    },
    "generate_regression_suite": {
        "description": "Gera suíte de regressão para um serviço.",
        "capability": "qa-engineer-mcp.generate_regression_suite",
        "required_scope": "qa-engineer-mcp:regression_suite:write",
        "resource_type": "regression_suite",
        "data_domain": "qa-engineer",
        "schema": _schema({
            "service": dict(_STR, description="Serviço alvo."),
            "test_cases": dict(_STR_ARR, description="Casos base da suíte (opcional)."),
        }),
    },
    "generate_smoke_test_suite": {
        "description": "Gera suíte de smoke test pós-deploy para um serviço.",
        "capability": "qa-engineer-mcp.generate_smoke_test_suite",
        "required_scope": "qa-engineer-mcp:smoke_suite:write",
        "resource_type": "smoke_suite",
        "data_domain": "operational",
        "schema": _schema({
            "service": dict(_STR, description="Serviço alvo."),
            "endpoints": dict(_STR_ARR, description="Endpoints de smoke (opcional)."),
        }),
    },
}

# qa-engineer-mcp não tem tool tokenless; a liveness é o /v1/health (CI-7).
_EXEMPT_TOOLS: frozenset[str] = frozenset()
# Denylist fail-safe: tools que retornam segredos NUNCA saem pelo gateway (CI-7).
_EXCLUDE_TOOLS: frozenset[str] = frozenset()

# Campos de policy repassados no /mcp/tools/list (o gateway lê estes campos).
_POLICY_FIELDS = ("capability", "required_scope", "resource_type", "data_domain")


# ── Verificação do inner Twin Token (STD-SEC-006 / CI-4/CI-5) ─────────────────

def _verify_inner_token(twin_token: str, settings: Settings) -> dict[str, Any]:
    """Re-verifica o inner Twin Token na PRÓPRIA audiência (mcp:qa-engineer-mcp).

    O gateway já verificou o front token; o qa-engineer é 'one more verified client'
    (defense in depth). RS256 via JWKS do platform-admin; audiência exata; jti
    obrigatório. Levanta em qualquer falha (fail-closed).
    """
    if not settings.mcp_twin_audience or not settings.url_admin_twin_jwks:
        raise PermissionError(
            "integração com o gateway não configurada: defina MCP_TWIN_AUDIENCE "
            "(mcp:qa-engineer-mcp) e URL_ADMIN_TWIN_JWKS (ver STD-SEC-006 / IT-006)."
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
    if name == "analyze_quality_requirement":
        return analyze_quality_requirement(
            requirement=args.get("requirement", ""), context=args.get("context")
        )
    if name == "classify_bug_severity":
        return classify_bug_severity(
            description=args.get("description", ""), impact=args.get("impact", "medium"),
            frequency=args.get("frequency", "sometimes"),
        )
    if name == "validate_story_testability":
        return validate_story_testability(
            story=args.get("story", ""), acceptance_criteria=args.get("acceptance_criteria")
        )
    if name == "review_test_coverage":
        return review_test_coverage(
            module=args.get("module", ""), current_coverage=args.get("current_coverage", 0.0)
        )
    if name == "generate_test_plan":
        return generate_test_plan(
            feature=args.get("feature", ""), scope=args.get("scope", "full"),
            team=args.get("team"),
        )
    if name == "generate_test_cases":
        return generate_test_cases(
            feature=args.get("feature", ""), test_type=args.get("test_type", "functional"),
            count=args.get("count", 5),
        )
    if name == "generate_gherkin_scenarios":
        return generate_gherkin_scenarios(
            feature=args.get("feature", ""), scenarios=args.get("scenarios")
        )
    if name == "generate_e2e_tests":
        return generate_e2e_tests(
            feature=args.get("feature", ""), framework=args.get("framework", "playwright"),
            base_url=args.get("base_url"),
        )
    if name == "generate_api_tests":
        return generate_api_tests(
            endpoint=args.get("endpoint", ""), method=args.get("method", "GET"),
            base_url=args.get("base_url"),
        )
    if name == "generate_unit_tests":
        return generate_unit_tests(
            module=args.get("module", ""), language=args.get("language", "python")
        )
    if name == "generate_playwright_tests":
        return generate_playwright_tests(
            feature=args.get("feature", ""), base_url=args.get("base_url")
        )
    if name == "generate_cypress_tests":
        return generate_cypress_tests(
            feature=args.get("feature", ""), base_url=args.get("base_url")
        )
    if name == "generate_postman_collection":
        return generate_postman_collection(
            api_name=args.get("api_name", ""), base_url=args.get("base_url"),
            endpoints=args.get("endpoints"),
        )
    if name == "generate_bug_report":
        return generate_bug_report(
            title=args.get("title", ""), steps=args.get("steps"),
            severity=args.get("severity", "P2"),
        )
    if name == "generate_quality_gate":
        return generate_quality_gate(
            service=args.get("service", ""), thresholds=args.get("thresholds")
        )
    if name == "generate_uat_checklist":
        return generate_uat_checklist(
            feature=args.get("feature", ""), stakeholders=args.get("stakeholders")
        )
    if name == "generate_k6_performance_test":
        return generate_k6_performance_test(
            endpoint=args.get("endpoint", ""), vus=args.get("vus", 10),
            duration=args.get("duration", "30s"),
        )
    if name == "generate_regression_suite":
        return generate_regression_suite(
            service=args.get("service", ""), test_cases=args.get("test_cases")
        )
    if name == "generate_smoke_test_suite":
        return generate_smoke_test_suite(
            service=args.get("service", ""), endpoints=args.get("endpoints")
        )
    raise KeyError(name)


# ── HTTP Sidecar ──────────────────────────────────────────────────────────────

def _build_http_app(settings: Settings) -> FastAPI:
    """Cria o sidecar HTTP (health + bridge governado /mcp/tools/*)."""
    app = FastAPI(
        title="qa-engineer-mcp API",
        version="0.1.0",
        docs_url="/docs" if settings.docs_enabled else None,   # false em todo ambiente
        redoc_url=None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
    )

    @app.get("/v1/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "service": "qa-engineer-mcp", "tools": len(_TOOL_SCHEMAS)}

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
    _log.info("qa_engineer_mcp_ready tools=%d", len(_TOOL_SCHEMAS))

    server: Server = Server("qa-engineer-mcp-server")

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
