# config-mcp-server

Sidecar **MCP** (`kind=mcp_http`, **Model C** — inner Twin Token) da persona
**config** do DevTeam. Persona **stateful**: serve credenciais, ambientes, tenants e
config de workspace. A persistência roda sobre o **ORM canônico**
(`platform_database.orm`), **tenant-scoped e dual-db** (credencial-zero, ORM-H-12):
o serviço só conhece o `tenant_id` (dos claims do inner token); a credencial do banco
do tenant vem de `ADMIN_DATAFORALL.PLATFORMS`. Uma única tabela `config_entries`
(chave natural `namespace + config_key`) por tenant; os valores continuam encriptados
com **Fernet** no `value_encrypted` (encriptação at-rest da app, defense-in-depth —
não delegada ao DB). Não há backend REST/Trinity, então não há `ServiceApiClient`.

Implementado em **Python** (`mcp` + FastAPI). Integra-se ao `platform-mcp-gateway`
conforme `STD-MCP-001` (contrato de integração) e `STD-SEC-006` (inner token).

## Transporte

- **stdio** (primário, MCP) + **sidecar HTTP** em `:MCP_PORT` (default `7100`):
  - `GET  /v1/health`      — liveness (sem token)
  - `GET  /mcp/tools/list` — catálogo governado (com metadados de policy por tool)
  - `POST /mcp/tools/call` — execução; exige **inner Twin Token** (`aud=mcp:config-mcp`),
    exceto `status`.

## Segurança (Tier-2)

- `enforce_security_invariants()` no boot (fail-fast): `DOCS_ENABLED=false` sempre,
  `MCP_TWIN_AUDIENCE=mcp:config-mcp`, e em **cloud** `URL_ADMIN_TWIN_JWKS` +
  `ADMIN_DB_HOST`/`ADMIN_DB_PASSWORD` (resolução credencial-zero do tenant) +
  `CONFIG_MCP_MASTER_KEY` obrigatórios (`STD-SEC-001/004/006`).
- `tenant_id` vem SEMPRE das claims do inner token — nunca de argumento do cliente
  (`INV-3`).
- Denylist fail-safe (`_EXCLUDE_TOOLS`): `get_credential` (devolve segredo em claro) e
  `set_credential_secure` (depende de TTY) NUNCA saem pelo gateway.
- Master key do store resolvida via **Vault** quando `VAULT_ADDR` está setado, com
  degradação graciosa p/ env (`src/config/secrets.py`). Nenhum segredo no código
  (`STD-SEC-004`).
- Logging estruturado JSON (`STD-OBS-001`, `src/config/logging.py`).

## Tools

Credenciais (`get`/`set`/`set_secure`/`list`/`delete`), ambientes
(`get_env_config`, `set_env_var`, `list_environments`, `sync_env_file`,
`read_env_file`, `audit_env_files`, `redact_env_secrets`, `push_env_to_store`),
workspace (`get`/`set`/`list_workspace_config`), sysinfo (`get_physical_info`) e
tenants (`get`/`set`/`list` + `get_session_tenant_config`).

## Dev

```bash
pip install -e ".[dev]"
python -m ruff check . && python -m mypy src
python -m pytest -q --cov=src --cov-fail-under=80
```

Registro no gateway: ver [`gateway/README.md`](./gateway/README.md).
