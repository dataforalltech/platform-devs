# services-mcp

Sidecar MCP (`kind=mcp_http`, Model C) do **services** — registry e monitoramento
dos serviços da plataforma dataforalltech, agregado atrás do MCP Gateway central
(`platform-mcp`). Python + `mcp` (stdio) + FastAPI (sidecar HTTP), backend
PostgreSQL via `psycopg2`.

## Integração (Model C / gateway-ready)

- **STD-MCP-001** — `/mcp/tools/list` emite, por tool, `inputSchema` +
  `capability` + `required_scope` + `resource_type` + `data_domain` (o gateway não
  deriva policy por nome).
- **STD-SEC-006** — `/mcp/tools/call` re-verifica o **inner Twin Token**
  (`aud=mcp:services-mcp`, RS256) via JWKS do platform-admin (defense in depth). O
  `tenant_id` vem SEMPRE dos claims do token, nunca de argumento do cliente.
- **STD-SEC-001** — Swagger/OpenAPI desabilitado (`DOCS_ENABLED=false`) em todo
  ambiente; `enforce_security_invariants()` faz fail-fast no boot.
- **STD-SEC-004** — nenhum segredo/host literal no código: `SERVICES_PG_*` vêm de
  env (ou Vault via `load_secret`, com degradação graciosa). Senha obrigatória em
  cloud.
- **STD-OBS-001** — logging estruturado em JSON (`configure_logging`); tokens e
  argumentos sensíveis nunca são logados.

## Transporte

- `stdio` (primário, MCP) + sidecar HTTP em `MCP_PORT` (default 7100):
  - `GET  /v1/health` — liveness (sem token)
  - `GET  /mcp/tools/list` — catálogo governado (metadados de policy)
  - `POST /mcp/tools/call` — execução (inner token obrigatório)

## Tools (32)

Registry (5), PortMap (2), Discovery (4), Composite (3), Gateway (3), Launch (2),
Env (5), Infra (3), Brokers (3), Logs (2). O catálogo completo com schemas está em
`src/server/mcp_server.py` (`_TOOL_SCHEMAS`).

## Configuração

Copie `.env.example` para `.env` (gitignored) e ajuste. Variáveis principais:
`RUNTIME_ENV` (`local|cloud`), `MCP_TWIN_AUDIENCE`, `URL_ADMIN_TWIN_JWKS`,
`MCP_PORT`, `SERVICES_PG_*`, `VAULT_ADDR` (opcional).

## Desenvolvimento

```bash
cd services-mcp-server
pip install -e ".[dev]"
python -m ruff check . && python -m mypy src
python -m pytest -q --cov=src --cov-fail-under=80
```
