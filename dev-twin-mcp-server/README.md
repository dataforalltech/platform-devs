# dev-twin-mcp-server

Sidecar **MCP** (`kind=mcp_http`, **Model C** — inner Twin Token) da persona
`dev-twin`. Fornece identidade/sessão de agentes e desenvolvedores e gerencia sua
própria tabela de tokens de acesso em PostgreSQL. Servidor **Python** agregado
atrás do `platform-mcp-gateway` — nunca exposto direto à internet (INV-1).

Namespace canônico: `dev-twin-mcp` (audiência do inner token: `mcp:dev-twin-mcp`).

## Tools

| Tool | Escopo | Descrição |
|---|---|---|
| `status` | `:read` (exempt, tokenless) | Status do servidor. |
| `authenticate` | `session:write` | 1ª tool da sessão — valida o token e carrega o perfil. |
| `whoami` | `session:read` | Identidade autenticada na sessão. |
| `get_twin_context` | `context:read` | Contexto completo (identidade + git/OS/hostname). |
| `refresh_context` | `context:write` | Recaptura o contexto de ambiente. |
| `context_status` | `context:read` | Métricas de uso do contexto (recomendação de `/compact`). |
| `register_token` | `token:write` (excludeTools) | Admin — registra usuário e emite token. |
| `revoke_token` | `token:write` | Admin — revoga token(s). |
| `rotate_token` | `token:write` (excludeTools) | Admin — rotaciona o token de um usuário. |
| `list_tokens` | `token:read` | Admin — lista metadados de tokens (sem valores). |

`register_token` e `rotate_token` retornam token em plaintext → ficam na denylist
`excludeTools` (CI-7): a provisão de tokens é bootstrap out-of-band, **nunca** pela
porta da frente da IA.

## Contrato com o gateway (STD-MCP-001)

- `GET  /v1/health` — liveness (sem token).
- `GET  /mcp/tools/list` — catálogo governado (com `capability`/`required_scope`/`resource_type`/`data_domain`).
- `POST /mcp/tools/call` — execução; o **inner Twin Token** (`mcp:dev-twin-mcp`, RS256,
  `jti`) é re-verificado via JWKS do `platform-admin` (defense in depth); o `tenant_id`
  vem SEMPRE dos claims, nunca de argumento do cliente (SEC-035 / INV-3).

Registro declarativo (pull-based) do serviço no gateway: ver [`gateway/`](./gateway/).

## Configuração (STD-SEC-004)

UM ÚNICO `.env` (ver [`.env.example`](./.env.example)); o comportamento por ambiente
é gated por `RUNTIME_ENV ∈ {local, cloud}`. A senha do DB nunca tem default no código
— vem de env ou do Vault (`VAULT_ADDR` setado → segredo `dev-twin-mcp/pg_password`,
com degradação graciosa p/ env). `DOCS_ENABLED=false` em todo ambiente (STD-SEC-001).

## Desenvolvimento

```bash
pip install -e ".[dev]"
python -m ruff check . && python -m mypy src
python -m pytest -q --cov=src --cov-fail-under=80
python -m src.server.mcp_server        # stdio + sidecar HTTP (:7100)
MCP_HTTP_ONLY=1 python -m src.server.mcp_server   # só o sidecar HTTP
```
