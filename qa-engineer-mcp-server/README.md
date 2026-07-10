# qa-engineer-mcp-server

Persona **QA Engineer** exposta como sidecar MCP `kind=mcp_http` no padrão canônico
**Model C** (inner Twin Token) do platform-service-template. Serviço Python
**compute-only**: gera artefatos de teste/QA a partir dos inputs — não há backend
REST/Trinity a chamar. Fica sempre atrás do `platform-mcp-gateway` (ingress só via
gateway, INV-1).

## Arquitetura

- Transporte: **stdio** (MCP primário) + **sidecar HTTP** (`:MCP_PORT`, default `7124`).
- `GET  /v1/health` — liveness (sem token).
- `GET  /mcp/tools/list` — catálogo governado (por tool: `inputSchema` +
  `capability` / `required_scope` / `resource_type` / `data_domain`).
- `POST /mcp/tools/call` — execução. Re-verifica o **inner Twin Token**
  (`aud=mcp:qa-engineer-mcp`, RS256 via JWKS do platform-admin, `jti` obrigatório —
  STD-SEC-006). O `tenant_id` vem SEMPRE das claims do token, nunca de argumento do
  cliente (SEC-035 / INV-3).

Standards: `STD-MCP-001` (contrato de integração), `STD-SEC-001/004/006` (RS256, um
único `.env`, inner token), `STD-OBS-001` (logging JSON estruturado).

## Tools (19)

**Leitura / análise (`:read`)** — `analyze_quality_requirement`,
`classify_bug_severity`, `validate_story_testability`, `review_test_coverage`.

**Geração de artefatos (`:write`)** — `generate_test_plan`, `generate_test_cases`,
`generate_gherkin_scenarios`, `generate_e2e_tests`, `generate_api_tests`,
`generate_unit_tests`, `generate_playwright_tests`, `generate_cypress_tests`,
`generate_postman_collection`, `generate_bug_report`, `generate_quality_gate`,
`generate_uat_checklist`, `generate_k6_performance_test`,
`generate_regression_suite`, `generate_smoke_test_suite`.

## Configuração

Um único `.env` (STD-SEC-004), discriminado por `RUNTIME_ENV ∈ {local, cloud}`.
Copie `.env.example` para `.env` e ajuste. Em `cloud`, `URL_ADMIN_TWIN_JWKS` é
obrigatório. Swagger/OpenAPI nunca é exposto (`DOCS_ENABLED=false`).

## Desenvolvimento

```bash
pip install -e ".[dev]"
python -m ruff check . && python -m mypy src
python -m pytest -q --cov=src --cov-fail-under=80
```

Registro no gateway: ver [`gateway/README.md`](./gateway/README.md).
