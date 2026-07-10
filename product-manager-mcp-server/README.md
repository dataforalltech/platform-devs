# product-manager-mcp-server

Sidecar MCP (`kind=mcp_http`, **Model C**) da persona **product-manager**, integrado ao
MCP Gateway central (`platform-mcp-gateway`). Persona **compute-only**: gera artefatos de
produto a partir dos inputs — não há backend REST/Trinity nem banco de dados.

## Arquitetura

- **Transporte:** stdio (MCP nativo) + sidecar HTTP em `:MCP_PORT` (default `7100`).
- **Model C (inner Twin Token):** o gateway já verifica o front token; o sidecar
  **re-verifica** o inner Twin Token na própria audiência `mcp:product-manager-mcp`
  (RS256 via JWKS do `platform-admin`), defense-in-depth (STD-SEC-006 / CI-4/CI-5).
- **tenant_id** vem SEMPRE dos claims do token verificado, nunca de argumento do
  cliente (SEC-035 / INV-3).
- **Segurança de boot:** `enforce_security_invariants()` faz fail-fast (DOCS_ENABLED
  proibido, audiência `mcp:<namespace>`, JWKS obrigatório em cloud — STD-SEC-001/006).
- **Observabilidade:** logging estruturado JSON no root logger (STD-OBS-001); tokens e
  argumentos sensíveis nunca são logados.

## Endpoints HTTP

| Método | Rota | Descrição |
|--------|------|-----------|
| GET  | `/v1/health`      | Liveness (sem token). |
| GET  | `/mcp/tools/list` | Catálogo governado (com `capability`/`required_scope`/`resource_type`/`data_domain`). |
| POST | `/mcp/tools/call` | Execução — inner Twin Token obrigatório, exceto tools em `_EXEMPT_TOOLS`. |

## Tools (5)

| Tool | Scope | Descrição |
|------|-------|-----------|
| `generate_feature_spec`      | `product-manager-mcp:feature_spec:write`   | Gera especificação de feature (deriva a saída de `feature`/`objective`). |
| `generate_go_to_market_brief`| `product-manager-mcp:gtm_brief:write`      | Gera brief de go-to-market. |
| `define_product_vision`      | `product-manager-mcp:product_vision:write` | Define visão, missão e metas de produto. |
| `generate_release_plan`      | `product-manager-mcp:release_plan:write`   | Gera plano de release faseado. |
| `status`                     | `product-manager-mcp:status:read`          | Status check (tokenless — `_EXEMPT_TOOLS`). |

## Configuração

Um único `.env` (STD-SEC-004); discriminador de ambiente `RUNTIME_ENV ∈ {local, cloud}`.
Copie `.env.example` para `.env` e ajuste.

| Var | Default | Descrição |
|-----|---------|-----------|
| `RUNTIME_ENV`          | `local` | `local` ou `cloud`. |
| `MCP_TWIN_AUDIENCE`    | `mcp:product-manager-mcp` | Audiência exata do inner token. |
| `URL_ADMIN_TWIN_JWKS`  | — | JWKS do `platform-admin` (obrigatório em `cloud`). |
| `MCP_PORT`             | `7100` | Porta do sidecar HTTP. |
| `DOCS_ENABLED`         | `false` | Swagger/OpenAPI — sempre `false` (STD-SEC-001). |
| `MCP_SERVICE_LOG_LEVEL`| `INFO` | Nível de log. |

## Desenvolvimento

```bash
pip install -e ".[dev]"
python -m ruff check .
python -m mypy src
python -m pytest -q --cov=src --cov-fail-under=80
```

## Execução

```bash
product-manager-mcp                    # stdio + sidecar HTTP
MCP_HTTP_ONLY=1 product-manager-mcp    # só o sidecar HTTP (uso típico atrás do gateway)
```
