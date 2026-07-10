# deploy-mcp-server

Sidecar **MCP** (`kind=mcp_http`, Model C) da persona **deploy** do DevTeam. Expõe 24
tools para Git, Pull Requests, GitHub Actions, pipelines CI/CD, Azure Container Registry
(ACR) e workspace local, todas atrás do `platform-mcp-gateway`.

Stack: Python 3.12, `mcp` (stdio) + FastAPI/uvicorn (sidecar HTTP), PyGithub. O backend
do serviço é a **GitHub REST API + ACR** via `src/knowledge/github_client.py` (Bearer =
GitHub PAT). Não há OAuth-PRM/FastMCP/REST-Trinity — a autorização é o **inner Twin
Token** (`aud=mcp:deploy-mcp`) re-verificado a cada `/mcp/tools/call` (STD-SEC-006).

## Tools (24)

| Grupo | Tools |
|---|---|
| Git (4) | `list_repos`, `create_branch`, `list_branches`, `commit_files` |
| PR (4) | `create_pr`, `get_pr`, `merge_pr`, `list_prs` |
| Workflow (4) | `trigger_workflow`, `list_workflow_runs`, `get_workflow_run`, `cancel_workflow_run` |
| Deploy (2) | `deploy`, `get_deploy_status` |
| Pipeline (2) | `scaffold_pipeline`, `get_pipeline_templates` |
| ACR (3) | `setup_repo`, `acr_build`, `list_acr_images` |
| Healthcheck (1) | `ensure_all_repos_healthy` |
| Workspace local (4) | `get_repos_root`, `set_repos_root`, `list_local_repos`, `clone_repo` |

## Endpoints (sidecar HTTP, `:MCP_PORT`, default 7100)

- `GET  /v1/health` — liveness (sem token).
- `GET  /mcp/tools/list` — catálogo governado (por tool: `inputSchema`, `capability`,
  `required_scope`, `resource_type`, `data_domain` — o gateway não deriva por nome).
- `POST /mcp/tools/call` — execução; exige o inner Twin Token em `params._meta.twin_token`
  (RS256 via JWKS do platform-admin, audiência `mcp:deploy-mcp`, `jti` obrigatório). O
  `tenant_id` vem sempre dos claims, nunca de argumento do cliente (SEC-035 / INV-3).

## Configuração

Um único `.env` (STD-SEC-004), discriminado por `RUNTIME_ENV ∈ {local, cloud}`. Veja
`.env.example`. Segredos (`DEPLOY_GITHUB_TOKEN`, `DEPLOY_ACR_PASSWORD`) vêm só do
ambiente — nunca do código. Em `cloud`, `URL_ADMIN_TWIN_JWKS` e `DEPLOY_GITHUB_TOKEN`
são obrigatórios (fail-fast no boot via `enforce_security_invariants`). `DOCS_ENABLED`
é sempre `false` (STD-SEC-001).

## Desenvolvimento

```bash
pip install -e ".[dev]"
python -m ruff check . && python -m mypy src
python -m pytest -q --cov=src --cov-fail-under=80
```

Registro no gateway (declarativo, pull-based): ver [`gateway/README.md`](./gateway/README.md).
