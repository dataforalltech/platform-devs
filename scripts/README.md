# scripts/

Utilitarios de CI/manutencao da plataforma.

## `check_mcp_dod.py` — Gate do Definition of Done (DoD) dos MCPs

Checker **estatico** (nao sobe servidor) que impoe o "Definition of Done" descrito em
[`MCP_SERVICE_STANDARD.md`](../MCP_SERVICE_STANDARD.md) §11. Varre os diretorios
`*-mcp-server/` que tenham `src/server/mcp_server.py` e verifica, para cada MCP, o padrao
canonico estabelecido por `security`/`qa-engineer`:

| Criterio (§11)                                   | Como e checado (AST / regex / pyproject)                       |
|--------------------------------------------------|----------------------------------------------------------------|
| Streamable HTTP via SDK oficial                  | usa `FastMCP(` e define `build_app(` e `build_mcp(`            |
| Auth no `/mcp`                                   | usa `BearerAuthMiddleware`                                      |
| Publica Protected Resource Metadata              | rota `/.well-known/oauth-protected-resource` via `custom_route`|
| Health publico                                   | rota `/v1/health` via `custom_route`                           |
| Escopo por ferramenta                            | `TOOL_REGISTRY` + funcao `_scope_for_request`                  |
| Zero token/segredo hardcoded                     | ausencia de `test-admin/developer/readonly-token` no dir       |
| Dep do SDK pinada                                | `pyproject.toml` declara `mcp>=1.10`                           |
| Deps de seguranca                                | `pyproject.toml` declara `pyjwt`, `cryptography`, `bcrypt`     |

Tambem checa o **gateway** (`mcp-gateway/`): que os tokens de teste nao existem no
codigo-fonte (arquivos em `tests/` sao ignorados — assercoes que verificam a rejeicao
desses tokens sao permitidas).

### Escopo do gate: migrados vs. legado

O DoD so vale para MCPs ja migrados para o template novo. O checker distingue os dois
casos pelo uso de `BearerAuthMiddleware` no `mcp_server.py`:

- **Migrado** — avaliado; DEVE cumprir todos os criterios ou o gate falha.
- **Legado** (servidor REST antigo, ainda nao portado) — reportado como **PENDENTE de
  migracao**; nao derruba o gate.

Isso trava regressoes nos 8 DevTeam migrados (security, qa-engineer, architecture, backend,
frontend, devops, product-owner, product-manager) + gateway, sem bloquear o CI por causa do
backlog de migracao.

### Uso

```bash
# Relatorio humano (pt-BR)
python scripts/check_mcp_dod.py

# Saida estruturada
python scripts/check_mcp_dod.py --json
```

**Exit code:** `0` se todos os MCPs migrados passam; `1` se algum falha.

**Encoding (Windows):** o console costuma ser cp1252. Rode com
`PYTHONIOENCODING=utf-8 PYTHONUTF8=1` para evitar `UnicodeEncodeError`.

Roda no CI via [`.github/workflows/mcp-dod.yml`](../.github/workflows/mcp-dod.yml).
