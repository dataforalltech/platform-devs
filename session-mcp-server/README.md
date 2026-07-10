# session-mcp-server

Sidecar **MCP (kind=`mcp_http`, Model C)** que persiste **sessões de trabalho** do
Claude Code — sessões, checkpoints, artefatos, tasks, dependências de serviço,
sugestões cross-repo e um audit trail de decisões. Fica atrás do
**platform-mcp-gateway** e é agregado no namespace `session-mcp`.

- **Runtime:** Python 3.12, `mcp` + FastAPI (sidecar HTTP).
- **Store:** SQLite embarcado, hermético (interface estilo psycopg2 em `src/db/store.py`).
  Nenhuma conexão de rede é aberta em runtime nem nos testes.
- **Integração:** contrato STD-MCP-001 (gateway) + STD-SEC-006 (inner Twin Token).

## Segurança (Tier-2)

- **Inner Twin Token (Model C):** `/mcp/tools/call` re-verifica o token na própria
  audiência `mcp:session-mcp` (RS256 via JWKS do platform-admin, `jti` obrigatório,
  fail-closed). `tenant_id` vem SEMPRE dos claims — nunca de argumento do cliente.
- **`enforce_security_invariants()`** (fail-fast no boot): `DOCS_ENABLED=false` em todo
  ambiente; audiência `mcp:<namespace>`; em `cloud`, `URL_ADMIN_TWIN_JWKS` e a senha do
  backend são obrigatórios.
- **Segredos (STD-SEC-004):** nenhum default com cara de credencial no código. A senha do
  Postgres é resolvida por `load_secret` (`src/config/secrets.py`): Vault (se `VAULT_ADDR`)
  → env → vazio, com degradação graciosa (o boot nunca quebra por causa do Vault).
- **Logging estruturado (STD-OBS-001):** `src/config/logging.py` emite JSON por linha; tokens
  e argumentos sensíveis nunca são logados.

## Endpoints (sidecar HTTP, `:MCP_PORT`, default 7100)

| Rota | Descrição |
|------|-----------|
| `GET  /v1/health`      | liveness (sem token) |
| `GET  /mcp/tools/list` | catálogo governado (capability, required_scope, resource_type, data_domain por tool) |
| `POST /mcp/tools/call` | execução (inner Twin Token obrigatório) |

## Tools (29, em 5 domínios)

- **Sessões (9):** `start_session`, `confirm_branch_created`, `save_checkpoint`,
  `update_session`, `add_artifact`, `list_sessions`, `get_session`, `resume_session`,
  `end_session`.
- **Tasks (8):** `add_task`, `approve_task`, `start_task`, `complete_task`, `fail_task`,
  `cancel_task`, `list_tasks`, `get_task`.
- **Dependências de serviço (3):** `add_service_dependency`, `list_service_dependencies`,
  `remove_service_dependency`.
- **Sugestões cross-repo (7):** `submit_suggestion`, `list_suggestions`, `get_suggestion`,
  `accept_suggestion`, `reject_suggestion`, `defer_suggestion`, `supersede_suggestion`.
- **Decisões / audit trail (2):** `list_decisions`, `get_decision`.

## Configuração

Copie `.env.example` para `.env` (gitignored) e ajuste. Único `.env`; o ambiente é
discriminado por `RUNTIME_ENV ∈ {local, cloud}`. Variáveis de backend usam o prefixo
`SESSION_` (ex.: `SESSION_PG_PASSWORD`).

## Desenvolvimento

```bash
pip install -e ".[dev]"
python -m ruff check . && python -m mypy src
python -m pytest -q --cov=src --cov-fail-under=80
```

Entrypoint: `session-mcp` (stdio + sidecar HTTP). `MCP_HTTP_ONLY=1` sobe só o sidecar
(uso típico atrás do gateway).

## Postgres (Fase 2)

As settings `SESSION_PG_*` e o `pg_dsn` já existem para um futuro dual-write
SQLite→PostgreSQL. Ainda **não** há sync em runtime — o SQLite embarcado é a fonte da
verdade e o backend continua hermético.
