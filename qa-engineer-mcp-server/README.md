# qa-engineer-mcp-server

Persona **QA Engineer** exposta como sidecar MCP `kind=mcp_http` no padrão canônico
**Model C** (inner Twin Token) do platform-service-template. Serviço Python
**stateful**: no modelo *"o agente gera o conteúdo, a tool persiste"*, o agente
chamador fornece o artefato (plano, caso, bug, código de teste) e as tools o
**persistem** no banco do tenant. A persistência roda 100% sobre o **ORM canônico**
(`platform_database.orm`), **tenant-scoped e dual-db**, credencial-zero (ORM-H-12):
o serviço só conhece o `tenant_id`; a credencial do banco vem de
`ADMIN_DATAFORALL.PLATFORMS`. Fica sempre atrás do `platform-mcp-gateway` (ingress só
via gateway, INV-1).

## Arquitetura

- Transporte: **stdio** (MCP primário — gateway-only: recusa fail-closed sem tenant)
  + **sidecar HTTP** (`:MCP_PORT`, default `7124`).
- `GET  /v1/health` — liveness (sem token).
- `GET  /mcp/tools/list` — catálogo governado (por tool: `inputSchema` +
  `capability` / `required_scope` / `resource_type` / `data_domain`).
- `POST /mcp/tools/call` — execução. Re-verifica o **inner Twin Token**
  (`aud=mcp:qa-engineer-mcp`, RS256 via JWKS do platform-admin, `jti` obrigatório —
  STD-SEC-006). O `tenant_id` vem SEMPRE das claims do token, nunca de argumento do
  cliente (SEC-035 / INV-3); a sessão do store é aberta credencial-zero por-request
  (`for_tenant`).

Standards: `STD-MCP-001` (contrato de integração), `STD-SEC-001/004/006` (RS256, um
único `.env`, inner token), `STD-OBS-001` (logging JSON estruturado).

## Modelo de dados (5 entidades, dual-db)

`qa_test_plans`, `qa_test_cases`, `qa_bug_reports`, `qa_quality_gates` (chave natural
única `service` → upsert), `qa_artifacts` (histórico append-only do código/cenário
gerado). Dados estruturados são JSON serializado em `TEXT` (dual-db safe).

## Tools (23) — CRUD que persiste

Cada entidade expõe `save`/`set` (persiste o artefato do agente), `list` (filtros),
`get` e `delete` (soft-delete); plans/cases/bugs também têm `update`:

- **Test Plans** — `save_test_plan`, `list_test_plans`, `get_test_plan`,
  `update_test_plan`, `delete_test_plan`.
- **Test Cases** — `save_test_case`, `list_test_cases`, `get_test_case`,
  `update_test_case`, `delete_test_case`.
- **Bug Reports** — `save_bug_report` (calcula severidade P1–P4 + score de
  impacto×frequência quando ausentes), `list_bug_reports`, `get_bug_report`,
  `update_bug_status`, `delete_bug_report`.
- **Quality Gates** — `set_quality_gate` (upsert por `service`), `list_quality_gates`,
  `get_quality_gate`, `delete_quality_gate`.
- **Artifacts** — `save_artifact` (kind ∈ e2e|api|unit|gherkin|playwright|cypress|
  postman|k6|regression|smoke|uat|coverage|analysis|testability), `list_artifacts`,
  `get_artifact`, `delete_artifact`.

## Configuração

Um único `.env` (STD-SEC-004), discriminado por `RUNTIME_ENV ∈ {local, cloud}`.
Copie `.env.example` para `.env` e ajuste (`DB_*` do tenant + `ADMIN_DB_*` que resolve
o tenant via PLATFORMS). Em `cloud`, `URL_ADMIN_TWIN_JWKS` e `ADMIN_DB_HOST`/
`ADMIN_DB_PASSWORD` são obrigatórios. Swagger/OpenAPI nunca é exposto
(`DOCS_ENABLED=false`).

## Desenvolvimento

```bash
pip install -e ".[dev]"
python -m ruff check . && python -m mypy src
python -m pytest -q --cov=src --cov-fail-under=80
```

Registro no gateway: ver [`gateway/README.md`](./gateway/README.md).
