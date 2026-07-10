# pipeline-mcp-server

Sidecar MCP (`kind=mcp_http`, **Model C**) que governa o pipeline DEV→HML→PROD dos
microserviços da plataforma dataforalltech. Persona **stateful**: mantém pipelines,
gates e promoções num **PostgreSQL** e fala com a **GitHub REST API** para criar/mergiar
PRs durante as promoções.

Integra-se ao MCP Gateway central conforme:
- `STD-MCP-001` — contrato de integração com o gateway (CI-1..CI-11)
- `STD-SEC-006` — inner Twin Token (audiência `mcp:pipeline-mcp`)
- `STD-SEC-001/004` — RS256 exclusivo, `/docs` desabilitado, segredos fora do código
- `STD-OBS-001` — logging estruturado JSON

## Regras de aprovação

| Transição            | Comportamento                                            |
|----------------------|---------------------------------------------------------|
| PRs → `develop` (DEV)| auto-aprova e mergia autonomamente se os gates passam    |
| `develop` → `homol`  | cria PR via GitHub e **aguarda aprovação humana**        |
| `homol` → `main`     | cria PR via GitHub e **aguarda aprovação humana**        |

## Tools (14)

**Pipeline (8):** `register_pipeline`, `get_pipeline`, `list_pipeline`,
`promote_service`, `approve_promotion`, `watch_prs`, `block_service`, `rollback`

**Gates (3):** `add_gate_result`, `get_gate_status`, `clear_gates`

**Histórico/Config (3):** `get_promotion_history`, `get_pipeline_overview`,
`set_pipeline_config`

Cada tool é publicada em `/mcp/tools/list` com os 4 campos de política que o gateway
lê (não deriva por nome): `capability`, `required_scope` (`dominio:tipo:acao`),
`resource_type`, `data_domain`.

## Segurança (Model C)

- **Inner Twin Token obrigatório** em toda execução (`/mcp/tools/call`): re-verificado
  na própria audiência (`mcp:pipeline-mcp`), RS256 via JWKS do platform-admin, `jti`
  obrigatório — fail-closed. Não há tool tokenless.
- **`tenant_id` sempre dos claims** do token verificado, nunca de argumento do cliente
  (SEC-035 / INV-3).
- **`enforce_security_invariants()`** roda no boot (fail-fast): `DOCS_ENABLED=false`,
  audiência `mcp:<namespace>`, e em `RUNTIME_ENV=cloud` exige `URL_ADMIN_TWIN_JWKS` e
  `PG_PASSWORD`.
- **Segredos**: a senha do DB é resolvida por `load_secret` (Vault quando `VAULT_ADDR`
  está setado, com degradação graciosa p/ env). Nenhum default com cara de credencial
  fica no código.

## HTTP sidecar (porta `MCP_PORT`, default 7100)

- `GET  /v1/health` — liveness (sem token)
- `GET  /mcp/tools/list` — catálogo governado (com metadados de policy)
- `POST /mcp/tools/call` — execução (inner token obrigatório)

## Configuração (env vars)

Um único `.env` (STD-SEC-004); ver `.env.example`. Discriminador de ambiente:
`RUNTIME_ENV ∈ {local, cloud}`.

| Variável                | Default              | Descrição                              |
|-------------------------|----------------------|----------------------------------------|
| `RUNTIME_ENV`           | `local`              | `local` \| `cloud`                     |
| `MCP_TWIN_AUDIENCE`     | `mcp:pipeline-mcp`   | audiência do inner token               |
| `URL_ADMIN_TWIN_JWKS`   | —                    | JWKS do platform-admin (req. em cloud) |
| `MCP_PORT`              | `7100`               | porta do sidecar HTTP                  |
| `DOCS_ENABLED`          | `false`             | Swagger nunca exposto                  |
| `MCP_SERVICE_LOG_LEVEL` | `INFO`               | nível de log                           |
| `PG_HOST`               | —                    | host do PostgreSQL                     |
| `PG_PORT`               | `5432`               | porta do PostgreSQL                    |
| `PG_DB`                 | `pipeline_mcp`       | database                               |
| `PG_USER`               | `postgres`           | usuário                                |
| `PG_PASSWORD`           | —                    | senha (env/Vault; req. em cloud)       |
| `PIPELINE_GITHUB_TOKEN` | —                    | token para criar/mergiar PRs           |
| `PIPELINE_GITHUB_ORG`   | —                    | org GitHub                             |

## Desenvolvimento

```bash
cd pipeline-mcp-server
pip install -e ".[dev]"
python -m ruff check .
python -m mypy src
python -m pytest -q --cov=src --cov-fail-under=80
```
