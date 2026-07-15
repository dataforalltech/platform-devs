# devops-mcp-server

Sidecar **MCP** (`kind=mcp_http`, **Model C** / inner Twin Token) da persona **DevOps** do
DevTeam, agregado pelo MCP Gateway central (`platform-mcp`). Persona **stateful** ("o agente
gera o conteúdo, a tool persiste"): o agente chamador fornece o artefato de infra-as-code
(Dockerfile, pipeline, chart, manifesto, registro de deploy) e as tools o **persistem** num
MySQL do tenant via ORM canônico (`platform_database.orm`) — **tenant-scoped, dual-db e
credencial-zero** (o serviço só conhece o `tenant_id`; a credencial do banco vem de
`ADMIN_DATAFORALL.PLATFORMS`).

Implementa o contrato de integração:
- `STD-MCP-001` — MCP Gateway Integration Contract (CI-1..CI-11)
- `STD-SEC-006` — Token Model C (inner Twin Token)
- `STD-SEC-001` — RS256 exclusivo, Swagger/OpenAPI nunca exposto
- `STD-SEC-004` — um único `.env`, discriminador `RUNTIME_ENV`
- `STD-OBS-001` — logging estruturado (JSON)

## Arquitetura

Transporte duplo: **stdio** (MCP nativo) + **sidecar HTTP** (`:MCP_PORT`, default `7100`).

| Rota | Descrição |
|------|-----------|
| `GET /v1/health` | liveness (sem token) |
| `GET /mcp/tools/list` | catálogo governado, com metadados de policy (`capability`, `required_scope`, `resource_type`, `data_domain`) |
| `POST /mcp/tools/call` | execução — inner Twin Token obrigatório (exceto tools exempt) |

Segurança (defense in depth): o gateway já verifica o front token; este sidecar
**re-verifica o inner Twin Token** na própria audiência (`mcp:devops-mcp`), RS256 via
JWKS do `platform-admin`, `jti` obrigatório, fail-closed. O `tenant_id` vem SEMPRE dos
claims do token verificado — nunca de argumento do cliente (SEC-035 / INV-3).

## Tools

Persistência CRUD para 5 entidades (22 tools). Todas exigem inner Twin Token (não há tool
tokenless — o liveness fica no `/v1/health`).

| Entidade | Tools | Chave |
|----------|-------|-------|
| **Artifact** (IaC gerado: dockerfile/github_actions/helm_chart/k8s_manifest/...) | `save_artifact`, `list_artifacts`, `get_artifact`, `delete_artifact` | histórico (`id`) |
| **Pipeline** (CI/CD) | `save_pipeline`, `list_pipelines`, `get_pipeline`, `update_pipeline`, `delete_pipeline` | histórico (`id`) |
| **Deployment** (evento de deploy) | `save_deployment`, `list_deployments`, `get_deployment`, `update_deployment_status`, `delete_deployment` | histórico (`id`) |
| **Environment** (cluster/ambiente) | `set_environment`, `list_environments`, `get_environment`, `delete_environment` | natural `name` (upsert) |
| **ServiceConfig** (defaults por serviço) | `set_service_config`, `list_service_configs`, `get_service_config`, `delete_service_config` | natural `service` (upsert) |

`save_deployment` dobra a função pura determinística `recommend_strategy(environment)`
(prod→`blue_green`, hml/staging→`rolling`, dev→`recreate`) quando `strategy` não é fornecida.

## Configuração

Copie `.env.example` para `.env` (gitignored) e ajuste. Variáveis principais:

- `RUNTIME_ENV` — `local` | `cloud` (em `cloud`, `URL_ADMIN_TWIN_JWKS` é obrigatório)
- `MCP_TWIN_AUDIENCE` — `mcp:devops-mcp` (audiência exata do inner token)
- `URL_ADMIN_TWIN_JWKS` — JWKS do emissor do twin token
- `MCP_PORT` — porta do sidecar HTTP (default `7100`)
- `DOCS_ENABLED` — `false` em todo ambiente (invariante STD-SEC-001)
- `DB_*` — backend do tenant (fallback compartilhado; `DB_ENGINE` decide o dialeto mysql/postgresql)
- `ADMIN_DB_*` — conexão admin que lê `ADMIN_DATAFORALL.PLATFORMS` (obrigatória em `cloud`)
- `VAULT_ADDR` — opt-in; resolve `DB_PASSWORD`/`ADMIN_DB_PASSWORD` via Vault com fallback p/ env

## Desenvolvimento

```bash
cd devops-mcp-server
pip install -e ".[dev]"

python -m ruff format .
python -m ruff check .
python -m mypy src
python -m pytest -q --cov=src --cov-fail-under=80
```

## Execução

```bash
devops-mcp                # stdio + sidecar HTTP
MCP_HTTP_ONLY=1 devops-mcp # só o sidecar HTTP (uso típico atrás do gateway)
```

Em produção o server sobe como container atrás do gateway; o ingress externo é
exclusivamente via `platform-mcp` (INV-1).
