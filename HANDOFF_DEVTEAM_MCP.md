# Handoff — Consolidação `devteam-mcp` (20 backends DevTeam → 1 server) — ✅ COMPLETA

> Companheiro do [`MCP_DEVTEAM_CONSOLIDATION_DESIGN.md`](MCP_DEVTEAM_CONSOLIDATION_DESIGN.md).
> Estado: **entregue, deployado na HML e provado ponta a ponta ao vivo.** Atualizado: 2026-07-18.

## TL;DR
Os ~20 MCP servers DevTeam/system (8 personas + 12 system) foram unidos num único **`devteam-mcp`**
(1 image, 1 deploy, 1 audiência `mcp:devteam-mcp`, **456 tools**). O gateway `platform-mcp` continua o ponto
único do cliente; mudou só o backend. **Deployado na HML, cutover dos 20 feito, o agente `platform-devs-agent`
roteia via `devteam-mcp`, e o E2E foi provado ao vivo** (runbook completo `done` + inbox HILT do console
carregando). Código na `develop` dos dois repos.

## Estado final no ar (HML)
- **Gateway `platform-mcp`** (`127.0.0.1:8090`): `devteam-mcp` registrado no `ADMIN_DATAFORALL.GATEWAY_MAPPING`
  (`name_microservice=platform-devteam-mcp` → namespace `devteam-mcp`, aud `mcp:devteam-mcp`). Os 20 mappings
  por-servidor foram REMOVIDOS (cutover). Catálogo agregado ~**1616 tools / 35 serviços** (era 2018/55 com os 20).
- **Container `platform-devteam-mcp`**: image `d4all.azurecr.io/dataforall/3.0/platform-devteam-mcp:develop-latest`
  (dual-db credencial-zero, `MCP_TWIN_AUDIENCE=mcp:devteam-mcp`, porta interna 7100). Serve 456 tools.
- **Agente** (`platform-devs-agent` sidecar + `platform-devs-agent-api`): image
  `platform-devs-agent:4b-consolidated-v2` (build do `develop` + shim de routing), **`DEV_GATEWAY_CONSOLIDATED=1`**
  no compose, `DEV_GATEWAY_PAT` = **SUPERADMIN_PAT** (tenant `dataforall`). Ambos `healthy`.
- **Os 20 containers-fonte** foram parados (`docker stop`, não `rm`) — fallback vivo p/ rollback.
- Host HML `i-002379444ffb89c10` (`us-east-1`), tudo via AWS SSM. Compose em `/opt/dataforall/deploy/services/devteam/`.

## Arquitetura
**devteam-mcp (agregador):** cada server-fonte virou `devteam-mcp-server/src/domains/<D>/` com `plugin.register()`
→ `{name, schemas, dispatch, ensure_schema}`. O agregador `src/server/mcp_server.py` é o boot/serve/segurança
Model-C compartilhado; auto-discovery dos domínios; roteamento longest-prefix; tools `<D>_<op>`;
`capability=devteam-mcp.<D>_<op>`, `required_scope=<D>:<res>:<ação>` (dropa o `-mcp` — **NÃO é gate**: o gate é a
audiência). 20 domínios: architecture, backend, frontend, devops, security, product-manager, product-owner,
qa-engineer (8 personas) + qa, test, deploy, session, ai-governance, config, services, docs, infra, pipeline,
dev-twin, audit.

**Routing do agente (shim strangler):** o agente fala nomes por-servidor (`<D>-mcp.<op>`) internamente (runbooks +
`platform-catalog` + capability/policy inalterados). A tradução ↔ `devteam-mcp.<D>_<op>` fica **confinada ao
`app/devs_agent/gateway/client.py`** (`translation.py`): `call_tool` traduz saída por-servidor→consolidado
(o gateway deriva `aud=mcp:devteam-mcp` no PAT-exchange — sem mudar token); `list_tools` traduz entrada
consolidado→por-servidor. **Gated por `DEV_GATEWAY_CONSOLIDATED`** (off = identidade/pré-cutover). Zero mudança
em auth/policy. 38 testes + suíte 229 verde; revisão adversarial CLEAR.

## Fases (histórico)
| Fase | Estado | Commit(s) |
|------|--------|-----------|
| 1. Esqueleto + piloto architecture | ✅ | `00a2022`→`a030367` |
| 2. Fan-out dos 19 domínios | ✅ | `203d4a1` |
| 3. Assemble (deps + Dockerfile + testes) | ✅ | `f9ccc10` |
| Prova local da image (build+boot healthy+contrato 20/456) | ✅ | `a3373fe` |
| 4. Build+push ACR → deploy strangler HML → GATEWAY_MAPPING → prova gateway | ✅ | `af494ea` |
| 5. Cutover (remover 20 mappings + parar 20 containers) | ✅ | `bcf6b61` |
| 4b. Routing do agente (shim) + PAT + base `develop` + HILT fix | ✅ E2E provado | `ecdc358` / agente `d4b2ceb` |

**E2E provado ao vivo:** `plan health_to_report` + `approve_and_execute` → os 3 passos (`check_health`,
`run_tests`, `generate_report`) `done` via `devteam-mcp`; inbox HILT do console carregando.

## Como reverter (tudo reversível)
- **Cutover** → `scratchpad/rollback_cutover.sh`: re-insere as 20 rows do backup
  `ADMIN_DATAFORALL.GATEWAY_MAPPING_BKP_devteam_cut` + `docker start` dos 20 + restart do `platform-mcp`.
- **Routing do agente** → `DEV_GATEWAY_CONSOLIDATED=0` no compose + recreate (volta ao comportamento pré-shim,
  mas pós-cutover isso dá `tool_not_found`; p/ funcionar sem devteam-mcp, reverter o cutover também).
- **Image do agente** → `IMAGE_TAG=develop-latest` no compose (a `develop-latest` da CI agora já tem o shim, pois o
  código está na develop; p/ pré-shim, usar uma tag anterior).
- **NÃO apagar** os diretórios `*-mcp-server/` do repo nem `docker rm` os 20 — são o fallback.

## Gotchas (herdados + descobertos — LEIA antes de mexer)
- ⚠️ **Buildar a image do agente do branch `develop`, NUNCA `main`** — o `main` estava atrás; buildar dele regrediu o
  agent-api (404 na rota `/plans` do inbox HILT). O shim já está na `develop` (`d4b2ceb`), então a `develop-latest` da
  CI passa a carregá-lo (flag off por default).
- ⚠️ **`required_scope` sem `-mcp` NÃO é gate** — o gate é a audiência (`mcp:devteam-mcp`), derivada de
  `name_microservice`. Sem coluna de scope no GATEWAY_MAPPING, sem enforcement no gateway; o backend só valida a aud.
- ⚠️ **PAT/tenant do agente** — `DEV_GATEWAY_PAT` tem que ser um PAT válido provisionado p/ o tenant (`from-pat 403`
  = mismatch). O SUPERADMIN_PAT (tenant `dataforall`) funciona. Provisão via platform-admin/governance.
- ⚠️ **`docker exec -i` quebra sob SSM** (sem TTY → exit≠0 → `set -e` mata o script): usar sem `-i` + `mysql -e`/`python -c` inline.
- ⚠️ **aws CLI v2 no Windows não aceita `-o json`** (é `--output json`) e precisa `PYTHONIOENCODING=utf-8` p/ saída não-ASCII.
- ⚠️ **`docker push` sai 0 mesmo com auth falhando** → validar o digest no ACR.
- ⚠️ **Restart do `platform-mcp` após mexer no GATEWAY_MAPPING** (registry lido no boot; re-agrega ~60s sozinho de qualquer forma).
- ⚠️ **Git Bash com PATH formato-Windows** (`;` + `C:\`) → external binaries "command not found"; prefixar
  `export PATH="/usr/bin:/bin:/mingw64/bin:/c/Program Files/Amazon/AWSCLIV2:..."`.
- ⚠️ **BuildKit trava** (`forwarding Ping: no such job`) → `docker buildx inspect --bootstrap desktop-linux`.
- ⚠️ **Classifier de segurança do Claude** bloqueia manuseio de PAT/segredo, `git push --force`, `gh pr create`, e às vezes
  `docker compose up`/`git push --delete` em contexto credencial-heavy → essas o **usuário** roda via bash. `git push --delete`
  trava em prompt `/dev/tty`; usar `gh api --method DELETE .../git/refs/heads/<branch>`.

## Pendências
- 🔴 **SEGURANÇA (urgente):** `platform-infra/dataforall-cloud-credentials.json` tem TODOS os segredos de prod em texto
  puro (SUPERADMIN_PAT + senha, OpenAI/Anthropic, `TOKEN_GITHUB`, DB, SMTP). **Rotacionar + `.gitignore`.**
- Outros consumidores diretos dos 20 namespaces (sessões Claude usando `mcp__dataforall__architecture-mcp_*`, o DAI)
  seguem no modelo antigo — migram pelo mesmo shim/flag ou pelo rollback quando precisarem.
- Follow-up de fidelidade (pós-prova, opcional): DRY dos 8 `config/settings.py` p/ a `DevteamSettings` compartilhada;
  migração "nativa" (rebindar `platform-catalog`/runbooks p/ `devteam-mcp.*` e remover o shim) — hoje o shim resolve.

## Ponteiros
- Código devteam-mcp: `devteam-mcp-server/` (na `develop` do platform-devs).
- Routing do agente: `platform-devs-agent` (repo separado), `app/devs_agent/gateway/translation.py` + `client.py`,
  na `develop` (`d4b2ceb`). Image `platform-devs-agent:4b-consolidated-v2`.
- Design: `MCP_DEVTEAM_CONSOLIDATION_DESIGN.md`.
- Memórias: `devteam-mcp-consolidation`, `devteam-orm-mysql-pilot`, `platform-devs-agent-build`,
  `devteam-hilt-e2e-live`, `saas-mcp-pat-connection-cloud`, `no-static-tenant-fallback`.
- Scripts desta execução (efêmeros, no scratchpad da sessão): `ssm_run.sh`, `deploy_devteam.sh`, `map_devteam2.sh`,
  `restart_gateway.sh`, `cutover.sh`, `rollback_cutover.sh`, `deploy_agent.sh`, `proof.py`.
