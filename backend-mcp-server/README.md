# backend-mcp — Backend Engineering MCP Server

Persona especialista em **Backend Engineering**: transforma requisitos, regras de
negócio e integrações em artefatos de API seguros, escaláveis e observáveis.

Sidecar **kind=mcp_http (Model C)**, gateway-ready, conforme:
- `STD-MCP-001` — contrato de integração com o MCP Gateway central (platform-mcp).
- `STD-SEC-006` — inner Twin Token (audiência `mcp:backend-mcp`, RS256 via JWKS do admin).
- `STD-SEC-001/004` — RS256 exclusivo, `/docs` desabilitado, um único `.env` (`RUNTIME_ENV`).
- `STD-OBS-001` — logging estruturado JSON.

Persona **compute-only**: gera os artefatos a partir dos inputs — não há backend
REST/Trinity a chamar, portanto sem `ServiceApiClient`.

## Transporte

- **stdio** (MCP primário).
- **HTTP sidecar** (`:MCP_PORT`, default `7100`):
  - `GET  /v1/health` — liveness (sem token).
  - `GET  /mcp/tools/list` — catálogo governado (com `capability`/`required_scope`/`resource_type`/`data_domain`).
  - `POST /mcp/tools/call` — execução; exige o inner Twin Token (exceto `_EXEMPT_TOOLS`), tenant vindo sempre dos claims.

`MCP_HTTP_ONLY=1` sobe apenas o sidecar HTTP (uso típico atrás do gateway).

## Tools (13)

Leitura / análise (`:read`):
- `analyze_backend_requirement` — analisa requisito e identifica entidades, permissões, integrações.
- `review_backend_code` — revisa código (segurança, performance, padrões, erros).
- `optimize_query` — otimiza query (índices, joins, N+1).

Geração de artefatos (`:write`):
- `generate_api_contract` — contrato de API (schemas, endpoints, status codes).
- `generate_auth_policy` — política de autenticação/autorização (`data_domain=security`).
- `generate_database_schema` — schema com índices e constraints.
- `generate_fastapi_router` — router FastAPI com validação.
- `generate_nestjs_controller` — controller NestJS.
- `generate_migration` — migration idempotente e reversível.
- `generate_repository_layer` — repository com CRUD.
- `generate_service_layer` — serviço com regra de negócio.
- `generate_openapi_spec` — especificação OpenAPI.
- `map_integration_flow` — fluxo de integração com sistemas externos (auth, erros, retry).

## Configuração

Copie `.env.example` para `.env` (gitignored) e ajuste. Discriminador de ambiente: `RUNTIME_ENV ∈ {local, cloud}`.

| Variável | Descrição |
|----------|-----------|
| `RUNTIME_ENV` | `local` ou `cloud` (em `cloud`, `URL_ADMIN_TWIN_JWKS` é obrigatório). |
| `MCP_TWIN_AUDIENCE` | Audiência exata do inner token: `mcp:backend-mcp`. |
| `URL_ADMIN_TWIN_JWKS` | JWKS do platform-admin (emissor do twin token). |
| `MCP_PORT` | Porta do sidecar HTTP (default `7100`). |
| `DOCS_ENABLED` | Deve ser `false` em todo ambiente (STD-SEC-001). |
| `MCP_SERVICE_LOG_LEVEL` | Nível de log (default `INFO`). |

## Desenvolvimento

```bash
cd backend-mcp-server
pip install -e ".[dev]"
python -m ruff format .
python -m ruff check .
python -m mypy src
python -m pytest -q --cov=src --cov-fail-under=80
```

## Execução

```bash
backend-mcp            # stdio + sidecar HTTP
MCP_HTTP_ONLY=1 backend-mcp   # apenas sidecar HTTP
```

## Docker

Build com contexto na raiz do repo (mesma convenção dos demais servers):

```bash
docker build -f backend-mcp-server/Dockerfile -t backend-mcp .
```
