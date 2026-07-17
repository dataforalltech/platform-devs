# devteam-mcp — Consolidação dos ~20 backends DevTeam num único server

**Decisão (2026-07-17):** unir os ~20 MCP servers DevTeam/system (8 personas + qa/test/deploy/session/
ai-governance/config/services/docs/infra/pipeline/dev-twin/audit) num **único `devteam-mcp`** — 1 image,
1 deploy, 1 restart. O gateway `platform-mcp` continua sendo o ponto único pro cliente; muda só o backend.

## Arquitetura — plugin por domínio (agregador)
Cada server-fonte vira um sub-pacote `devteam-mcp-server/src/domains/<domain>/` que EXPÕE um `register()`:
```
register() -> {
  "name": str,                  # a chave/prefixo do domínio (ex.: "architecture", "ai-governance")
  "schemas": dict[str, meta],   # _TOOL_SCHEMAS do domínio, CHAVES prefixadas: "<domain>_<op>"
  "dispatch": async fn(name, args, session) -> dict,   # constrói a(s) Store(s) sobre a sessão e roteia
  "ensure_schema": async fn(pool, engine),  # bootstrap das tabelas do domínio
}
```
O **agregador** `src/server/mcp_server.py`:
- Faz `_TOOL_SCHEMAS = {**dominio.schemas ...}` de todos os domínios (chaves já prefixadas → sem colisão).
- `_dispatch(name, args, session)`: por **longest-prefix-match** (`name.startswith(f"{key}_")`, maior chave vence),
  instancia `domain.store_cls(session)` e chama o dispatch do domínio.
- `_ensure_tenant_schema`: chama o `ensure_schema` de TODOS os domínios (todas as tabelas no schema do tenant).
- Serve UM `/mcp/tools/list` + `/mcp/tools/call`, **`aud=mcp:devteam-mcp`**, `NAMESPACE=devteam-mcp`.

**Registry por auto-discovery** (`src/domains/__init__.py`): varre os sub-pacotes e pluga cada `plugin.register()`.
Adicionar domínio = **soltar o pacote** (NÃO editar `__init__.py`) → fan-out de 1 agente/domínio sem conflito de merge.
Um domínio meio-construído é PULADO com log (não derruba o import); no assemble asserta-se que os 20 carregaram.

**Invariante de roteamento:** a chave do domínio (`DOMAIN`) É o prefixo de tool; o roteamento é longest-prefix, então
chaves com hífen são OK (`product-owner`, `ai-governance`, `dev-twin`, `qa-engineer`). Colisão de prefixo só ocorreria
se uma chave fosse prefixo-com-`_` de outra — mantê-las hifenizadas (nunca `<a>_<b>` como chave) garante disjunção
(`qa` vs `qa-engineer` não colidem: `"qa-engineer_x".startswith("qa_")` é falso).

## Naming + colisões (resolve a P2 de brinde)
Num server só os nomes de op têm que ser únicos, e há **32 colisões** (ex.: `save_artifact` em 6 personas).
→ chave/nome de op = **`<domain>_<op>`** (ex.: `architecture_save_artifact`, `backend_save_artifact`).
No gateway: `devteam-mcp.architecture_save_artifact`. O `capability` fica `devteam-mcp.<domain>_<op>`; o
`required_scope` PRESERVA `<domain>:<recurso>:<ação>` (least-privilege por-tool intacto); `data_domain`
mantém o domínio original. **O agente roteia por `capability`/`data_domain` (metadados), não por nome de
server** → o roteamento por persona sobrevive; só o `tool_matrix` do platform-devs-agent passa a ser
por-capability (não por-server).

## Store / segurança
- 1 pool por tenant (credencial-zero, `for_tenant`); cada domínio mantém sua Store (opera na sessão
  compartilhada). Todas as tabelas dos 20 domínios coexistem no schema do tenant.
- 1 `aud=mcp:devteam-mcp`, 1 `_verify_inner_token` (Model-C). Deps = união (database/tenant/core-lib +
  extras dos domínios pesados: deploy=GitHub, infra=terraform/checkov CLIs — no Dockerfile).

## Migração — strangler (zero-downtime, reversível)
1. Construir `devteam-mcp-server` (agregador + 20 domínios).
2. Build image `platform-devteam-mcp:develop-latest` (contexto=repo-root, `--secret github_token`).
3. Deploy AO LADO dos 20 (novo container no `services/devteam/docker-compose.yml`).
4. Add 1 linha no `GATEWAY_MAPPING` (`aud=mcp:devteam-mcp`) — restart do gateway → tools aparecem.
5. Validar no gateway (tools por domínio acessíveis, roteamento por capability). Atualizar `tool_matrix`.
6. Cortar: remover as ~20 mappings antigas; aposentar os 20 containers. Reverter = re-add as linhas.

## Fases
1. **Esqueleto + piloto** (ESTA fase): scaffold do pacote + agregador + migrar **architecture** (18 tools)
   como referência → py_compile/ruff/mypy/pytest verdes + tools registrando com prefixo.
2. **Fan-out**: migrar os 19 domínios restantes p/ `src/domains/<domain>/` (paralelo, 1 agente por domínio,
   copiando tools/store/models + `plugin.py`).
3. **Assemble + deps + Dockerfile + pyproject** (união) + testes de integração do agregador.
4. **Build + deploy strangler + prova no gateway** + atualizar tool_matrix do agente.
5. Aposentar os 20; atualizar `TOOLS_LIVE_INVENTORY.csv` + docs.
