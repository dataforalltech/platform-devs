# Handoff — Consolidação `devteam-mcp` (20 backends DevTeam → 1 server)

> Companheiro operacional do [`MCP_DEVTEAM_CONSOLIDATION_DESIGN.md`](MCP_DEVTEAM_CONSOLIDATION_DESIGN.md).
> Este doc é o "retome daqui": estado exato, o que já foi provado, e os comandos das fases que faltam.
> Atualizado: 2026-07-17.

## TL;DR
Unir os ~20 MCP servers DevTeam/system num único **`devteam-mcp-server/`** (1 image, 1 deploy, 1 audiência
`mcp:devteam-mcp`). O gateway `platform-mcp` continua o ponto único do cliente; muda só o backend.
**Fases 1–3 (código) COMPLETAS e verificadas localmente. Falta a Fase 4 (build→ACR→HML→gateway) — shared-infra,
aguardando autorização.**

- **Branch:** `feat/devteam-mcp-consolidation` (no repo `platform-devs`)
- **20 domínios / 456 tools** carregam juntos; contrato 0 violações; ruff/black/pytest verdes.
- **NÃO deployado ainda.** Os 20 servers-fonte continuam intactos e rodando (strangler — reversível).

## Estado por fase
| Fase | Status | Commit |
|------|--------|--------|
| 1. Esqueleto + piloto (`architecture`, 21 tools) | ✅ | `00a2022`→`a030367` |
| 2. Fan-out dos 19 domínios (workflow build→verify) | ✅ | `203d4a1` |
| 3. Assemble (união de deps + gates integrados + testes generalizados) | ✅ | `f9ccc10` |
| Prova local do build da image (deps privadas + venv limpo) | 🔄 em curso | — |
| 4. Build+push ACR → deploy strangler HML → `GATEWAY_MAPPING` → prova no gateway → `tool_matrix` | ⏳ | — |
| 5. Aposentar os 20 containers + atualizar `TOOLS_LIVE_INVENTORY.csv`/docs | ⏳ | — |

## Arquitetura (resumo — detalhes no design doc)
- **Agregador** `devteam-mcp-server/src/server/mcp_server.py`: boot/serve/segurança Model-C compartilhado
  (FastAPI + inner-token `aud=mcp:devteam-mcp` + tenant plumbing credencial-zero), parametrizado pelos domínios.
- **Domínio** = `src/domains/<D>/` com `plugin.register() -> {name, schemas, dispatch, ensure_schema}`.
  `dispatch(name, args, session)` — **o plugin constrói sua(s) Store(s) da sessão** (Contract B; uniforme
  single/multi-store).
- **Registry auto-discovery** (`src/domains/__init__.py`): varre subpacotes, pluga cada `register()`, pula-com-log
  domínio quebrado. Adicionar domínio = soltar o pacote (não edita `__init__.py`).
- **Roteamento longest-prefix**; chaves de domínio hifenizadas (sem colisão). Tools prefixadas `<D>_<op>`.
- **`_meta` transform:** `capability=devteam-mcp.<D>_<op>`, `required_scope=<D>:<res>:<ação>` (dropa `-mcp`);
  `data_domain`/`resource_type`/`description`/`schema` inalterados.
- **20 domínios:** architecture, backend, frontend, devops, security, product-manager, product-owner, qa-engineer
  (8 personas) + qa, test, deploy, session, ai-governance, config, services, docs, infra, pipeline, dev-twin, audit.

## Já verificado (NÃO precisa refazer)
- Import agregado: 20 domínios carregam via auto-discovery, **456 tools**, contrato 0 violações
  (prefixo/capability/required_scope corretos em todos).
- `ruff check src` + `black --check` (346 arquivos) + `pytest tests/` (9 testes, generalizados p/ N domínios) verdes.
- **Cópia fiel** (diff/checksum vs fonte): tools/db/models byte-idênticos; único delta = `infra/tools/infracost_tool.py`
  (ternário normalizado pelo black — semanticamente idêntico).
- **Dispatch cobre TODAS as ops** nos 20 domínios (0 rotas faltando).
- `get_settings()` de cada domínio funciona no env consolidado (lê `mcp:devteam-mcp` compartilhado; sem conflito).
- Os 4 domínios cujo verify-agent caiu no session-limit (dev-twin, audit, docs, infra) foram verificados à mão
  pelos checks acima.

**Re-provar tudo rápido:**
```bash
cd platform-devs/devteam-mcp-server
ruff check src && python -m black --check --line-length 110 src && python -m pytest tests -q -o addopts=""
python -c "from src.domains import DOMAINS; print(len(DOMAINS), sum(len(d['schemas']) for d in DOMAINS))"  # 20 456
```

## Fase 4 — build + deploy strangler (SHARED-INFRA — pausar p/ autorização)
Padrão idêntico ao dos 20 servers (ver `scratchpad/build_backend.sh` e a memória `devteam-orm-mysql-pilot`).

1. **Build local (já validando):** `scratchpad/build_devteam_local.sh` — `gh auth token`→temp→
   `docker build -f devteam-mcp-server/Dockerfile --secret id=github_token,src=<tmp> .` (contexto = raiz do repo).
2. **Build+push ACR:** tag `d4all.azurecr.io/dataforall/3.0/platform-devteam-mcp:develop-latest`; `az acr login --name d4all`;
   `docker push`; **validar o digest ACR == local** (⚠️ `docker push` sai 0 mesmo falhando auth → sempre conferir digest).
3. **Deploy HML** (host `i-002379444ffb89c10` / `dataforall-hml-host`, via AWS SSM `scratchpad/ssm_run.sh`):
   adicionar 1 serviço `platform-devteam-mcp` em `/opt/dataforall/deploy/services/devteam/docker-compose.yml`
   (env: `DB_*`/`ADMIN_DB_*` dual-db, `MCP_TWIN_AUDIENCE=mcp:devteam-mcp`, `URL_ADMIN_TWIN_JWKS`, `MCP_PORT=7100`,
   `DOCS_ENABLED=false`); `docker compose ... up -d platform-devteam-mcp`; esperar health.
4. **`GATEWAY_MAPPING`:** inserir 1 row `kind=mcp_http`, `aud=mcp:devteam-mcp`, url do novo container →
   **RESTART do `platform-mcp`** (registry lido só no boot — obrigatório).
5. **Prova no gateway:** `/mcp/tools/list` via PAT mostra `devteam-mcp.*` (456 tools por capability). Rodar 1 tool
   por-domínio (ex.: `devteam-mcp.architecture_save_artifact`) provando a cadeia PAT→gateway→devteam-mcp→dual-db.
6. **`tool_matrix`** do `platform-devs-agent`: passa a rotear por **capability/data_domain** (não por-server) —
   o `data_domain` de cada tool preserva o domínio original, então o roteamento por persona sobrevive.

### ⚠️ Risco #1 a validar na prova (passo 5): `required_scope` sem `-mcp`
As tools consolidadas usam `required_scope=<D>:<res>:<ação>` (ex.: `architecture:artifact:write`), dropando o
antigo `architecture-mcp:`. Se o gateway casa scope do twin contra o `required_scope`, os twins do tenant precisam
ter scope amplo/wildcard OU o mapeamento tem que aceitar o novo formato. **Confirmar na primeira chamada
autenticada**; se negar, o fix é 1 linha no `_meta` de cada `catalog.py` (voltar o prefixo) OU ajustar os scopes
dos twins. (No piloto architecture, revisado 0.92, já se usou o formato sem `-mcp`.)

## Fase 5 — cutover
Após a prova verde: remover as ~20 mappings antigas do `GATEWAY_MAPPING` + parar os 20 containers-fonte
(reverter = re-add as linhas). Atualizar `TOOLS_LIVE_INVENTORY.csv` e docs (ORCHESTRATION/MCP_TOOLS_REFERENCE).
**Não apagar os diretórios `*-mcp-server/` do repo** até o cutover estar estável (são o fallback).

## Desvios de fidelidade aceitos (follow-up pós-prova; fidelidade > DRY numa migração strangler)
- **8 domínios mantiveram `config/settings.py`** (referenciado pelos tools; passivo — sem `configure()` no import,
  campos DB_* inertes pois os stores usam a sessão do agregador). Follow-up: DRY p/ a `DevteamSettings` compartilhada.
- **`ai-governance`**: fonte sem `_dispatch` → roteamento extraído do `call_tool`; multi-store (SuggestionStore +
  AdrStore/AuditStore construídos da sessão); `_POLICY`/`_TENANT_SCOPED_TOOLS` preservados.
- **`qa`**: `dispatch(name, args, settings, store)` com `_QASettings` inline (knobs de compute).
- **`infra`**: `AllocatorStore` (db/allocator_store.py) + `models/` pacote + provisioner/ssh_key; CLIs
  terraform/checkov/infracost são runtime (Dockerfile não instala — erram graciosamente, igual ao fonte).

## Gotchas de infra (herdados dos ciclos anteriores)
- **Restart do `platform-mcp` obrigatório** após mexer no `GATEWAY_MAPPING` (registry só no boot).
- **SSM:** saída não-ASCII zera o output; limite ~24KB; `/tmp` não persiste entre invocações; heredoc via stdin corrompe.
  Scripts ASCII-only, single-invocation.
- **`docker push` sai 0 mesmo com auth falhando** → validar o digest no ACR.
- **Deploy drift:** imagens on-box podem atrasar vs develop; validar compose+imagem no box, não só o repo.

## Outras frentes abertas nesta sessão (fora da consolidação)
- Login `devs.dataforall.tech` **corrigido e ao vivo**; HILT E2E provado no tenant devteam. (memórias
  `devteam-hilt-e2e-live`, `platform-devs-agent-build`.)
- **CI do `platform-devs-agent`**: falta o secret `TOKEN_GITHUB` no GitHub (task #31 — só o usuário cria).
- **P2/P3** (consolidar sobreposições / podar tools) da iniciativa de organização: a consolidação resolve P2
  "de brinde" (naming por-domínio elimina as colisões). (memória `mcp-tools-organization`.)

## Ponteiros
- Design: `MCP_DEVTEAM_CONSOLIDATION_DESIGN.md` · Código: `devteam-mcp-server/`
- Memórias: `devteam-mcp-consolidation`, `devteam-orm-mysql-pilot`, `platform-devs-agent-build`, `no-static-tenant-fallback`
- Scripts de build/deploy reusáveis: `scratchpad/build_backend.sh`, `scratchpad/build_devteam_local.sh`, `scratchpad/ssm_run.sh`
