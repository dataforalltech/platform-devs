# devops-mcp-server

Sidecar **MCP** (`kind=mcp_http`, **Model C** / inner Twin Token) da persona **DevOps** do
DevTeam, agregado pelo MCP Gateway central (`platform-mcp`). Persona **compute-only**:
gera artefatos de DevOps/infra a partir dos inputs — não há backend REST/Trinity a chamar.

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

| Tool | Scope | Descrição |
|------|-------|-----------|
| `status` | `devops-mcp:status:read` | liveness stub (exempt / tokenless) |
| `generate_kubernetes_manifest` | `devops-mcp:k8s_manifest:write` | Deployment, Service, ConfigMap |
| `generate_dockerfile` | `devops-mcp:dockerfile:write` | Dockerfile otimizado |
| `generate_github_actions_pipeline` | `devops-mcp:pipeline:write` | pipeline CI/CD GitHub Actions |
| `generate_helm_chart` | `devops-mcp:helm_chart:write` | Helm Chart |

## Configuração

Copie `.env.example` para `.env` (gitignored) e ajuste. Variáveis principais:

- `RUNTIME_ENV` — `local` | `cloud` (em `cloud`, `URL_ADMIN_TWIN_JWKS` é obrigatório)
- `MCP_TWIN_AUDIENCE` — `mcp:devops-mcp` (audiência exata do inner token)
- `URL_ADMIN_TWIN_JWKS` — JWKS do emissor do twin token
- `MCP_PORT` — porta do sidecar HTTP (default `7100`)
- `DOCS_ENABLED` — `false` em todo ambiente (invariante STD-SEC-001)

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
