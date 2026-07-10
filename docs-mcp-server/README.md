# docs-mcp-server

Sidecar **MCP** (`kind=mcp_http`, **Model C** — inner Twin Token) que padroniza,
valida e audita documentação de repositórios. Persiste índice e histórico de
auditoria num PostgreSQL próprio (`src/db/store.py`). Agregado pelo
`platform-mcp-gateway` sob o namespace `docs-mcp` — **nunca** exposto direto à
internet (ingress só via gateway, INV-1).

- **Runtime:** Python 3.12, `mcp` + FastAPI (sidecar HTTP).
- **Contrato:** STD-MCP-001 (integração com o gateway) e STD-SEC-006 (inner token).
- **Compliance Tier-2:** STD-SEC-001/004/006 + STD-OBS-001
  (fail-fast no boot via `enforce_security_invariants`, logging JSON estruturado,
  segredos via env/Vault, `/docs` sempre desabilitado).

## Tools (14)

| Grupo | Tools |
|---|---|
| Scan/índice | `scan_docs`, `search_docs`, `get_doc_tree` |
| Validação | `validate_doc`, `check_links`, `check_required_docs`, `lint_markdown` |
| Templates | `list_templates`, `generate_doc` |
| Auditoria | `check_doc_standards`, `audit_repo`, `find_stale_docs`, `get_audit_history`, `generate_doc_report` |

Cada tool declara os 4 campos de política que o gateway lê em `/mcp/tools/list`
(`capability`, `required_scope`, `resource_type`, `data_domain`).

## Endpoints do sidecar (`:MCP_PORT`, default 7100)

| Método | Rota | Descrição |
|---|---|---|
| GET | `/v1/health` | liveness (sem token) |
| GET | `/mcp/tools/list` | catálogo governado (com metadados de policy) |
| POST | `/mcp/tools/call` | execução — inner Twin Token obrigatório (`aud=mcp:docs-mcp`) |

O `tenant_id` vem SEMPRE dos claims do token verificado, nunca de argumento do
cliente (SEC-035 / INV-3).

## Configuração

Copie `.env.example` para `.env` (gitignored). Discriminador de ambiente:
`RUNTIME_ENV ∈ {local, cloud}`. A senha do banco (`DOCS_PG_PASSWORD`) **nunca** é
versionada — vem de env ou do Vault (`VAULT_ADDR` setado → chave
`docs-mcp/pg_password`, com degradação graciosa p/ env). Registro no gateway: ver
[`gateway/README.md`](./gateway/README.md).

## Desenvolvimento

```bash
pip install -e ".[dev]"
python -m ruff check . && python -m mypy src
python -m pytest -q --cov=src --cov-fail-under=80
```
