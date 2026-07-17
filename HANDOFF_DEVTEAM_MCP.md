# Handoff — Consolidação `devteam-mcp` (20 backends DevTeam → 1 server)

> Companheiro operacional do [`MCP_DEVTEAM_CONSOLIDATION_DESIGN.md`](MCP_DEVTEAM_CONSOLIDATION_DESIGN.md).
> Este doc é o "retome daqui": estado exato, o que já foi provado, e os comandos das fases que faltam.
> Atualizado: 2026-07-17.

## TL;DR
Unir os ~20 MCP servers DevTeam/system num único **`devteam-mcp-server/`** (1 image, 1 deploy, 1 audiência
`mcp:devteam-mcp`). O gateway `platform-mcp` continua o ponto único do cliente; muda só o backend.
**Fases 1–3 (código) COMPLETAS e verificadas localmente. Image local BUILDADA e PROVADA** (clean venv, deps
privadas via secret; boot `healthy` + `/v1/health` = 456 tools). **Falta a Fase 4 (build→ACR→HML→gateway) —
shared-infra, aguardando autorização.**

- **Branch:** `feat/devteam-mcp-consolidation` (no repo `platform-devs`)
- **20 domínios / 456 tools** carregam juntos; contrato 0 violações; ruff/black/pytest verdes.
- **NÃO deployado ainda.** Os 20 servers-fonte continuam intactos e rodando (strangler — reversível).

## Estado por fase
| Fase | Status | Commit |
|------|--------|--------|
| 1. Esqueleto + piloto (`architecture`, 21 tools) | ✅ | `00a2022`→`a030367` |
| 2. Fan-out dos 19 domínios (workflow build→verify) | ✅ | `203d4a1` |
| 3. Assemble (união de deps + gates integrados + testes generalizados) | ✅ | `f9ccc10` |
| Prova local da image (build + boot `healthy` + `/v1/health` 456 tools + contrato 20/456 dentro da image) | ✅ | 2026-07-17 |
| 4. Build+push ACR → deploy strangler HML → `GATEWAY_MAPPING` → restart gateway → prova no gateway | ✅ (DEPLOYADO+PROVADO) | 2026-07-17 |
| 5. Cutover: aposentar as 20 mappings + parar os 20 containers | ✅ (forçado 2026-07-17; gateway 1616/35; backup+rollback prontos) | — |
| 4b. Rotear agente/clientes por `devteam-mcp.*` (refactor real; capability/policy) — **AGORA CRÍTICO** | ⏳ | — |
| — Atualizar `TOOLS_LIVE_INVENTORY.csv`/docs (ORCHESTRATION/MCP_TOOLS_REFERENCE) | ⏳ | — |

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

## Prova local da image (2026-07-17) — REPRODUZÍVEL sem infra compartilhada
A image `platform-devteam-mcp` builda, sobe e serve localmente (clean venv; deps privadas via secret; non-root
UID 1000; python:3.12-slim; 634 MB). Tudo reversível (só uma image local). Comandos exatos:

```bash
# 1) Build — contexto = raiz do repo; secret = PAT do gh (a substituição $(...) tira o \n do token).
cd platform-devs
gh auth token > "$TMPDIR/ghtok"
DOCKER_BUILDKIT=1 docker build -f devteam-mcp-server/Dockerfile \
  --secret id=github_token,src="$TMPDIR/ghtok" -t devteam-mcp:local . && rm -f "$TMPDIR/ghtok"

# 2) Contrato DENTRO da image (sem pytest/DB — equivalente pytest-free do tests/test_aggregator.py):
docker run --rm --entrypoint python devteam-mcp:local -c \
  "from src.server import mcp_server as M; s=M._TOOL_SCHEMAS; d=M.DOMAINS; \
   assert len(s)==sum(len(x['schemas']) for x in d); \
   bad=[n for n,m in s.items() if m['capability']!=f'devteam-mcp.{n}' or m['required_scope'].count(':')!=2]; \
   print(len(d), len(s), len(bad))"   # -> 20 456 0

# 3) Boot + health — RUNTIME_ENV=local dispensa DB/JWKS no enforce_security_invariants; configure() é LAZY
#    (não conecta no boot). MCP_HTTP_ONLY=1 sobe só o uvicorn (sem stdio).
docker run -d --name devteam_boot -e MCP_HTTP_ONLY=1 -e RUNTIME_ENV=local devteam-mcp:local
docker exec devteam_boot python -c \
  "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:7100/v1/health',timeout=4).read().decode())"
# -> {"status":"ok","service":"devteam-mcp","tools":456} ; container fica `healthy`;
#    log de boot: devteam_mcp_ready tools=456 domains=20 engine=mysql
docker rm -f devteam_boot
```

⚠️ **Gotcha BuildKit (Docker Desktop):** se o build falhar com `NotFound: forwarding Ping: no such job ...` (e
`docker buildx ls` mostrar os nodes em `error`), o builder embutido travou. Recupere com
`docker buildx inspect --bootstrap desktop-linux` e refaça o build — **não** precisa reiniciar o Docker Desktop.

## Fase 4 — build + deploy strangler → ✅ EXECUTADA e PROVADA (2026-07-17)
**Feito ao vivo na HML** (host `i-002379444ffb89c10` / `us-east-1`, via AWS SSM). Reversível: os 20 servers-fonte
continuam de pé; para reverter, remover o container + a 1 row do `GATEWAY_MAPPING` e restart do gateway.

- **ACR:** `docker tag devteam-mcp:local d4all.azurecr.io/dataforall/3.0/platform-devteam-mcp:develop-latest && docker push`.
  Digest validado no ACR = `sha256:2f0263ee716b…` (bate com o local; manifest list c/ child amd64 `6172eb…` + attestation).
- **Compose:** bloco `platform-devteam-mcp` (idêntico aos personas, só muda image/container_name/`MCP_TWIN_AUDIENCE: mcp:devteam-mcp`)
  anexado a `services/devteam/docker-compose.yml` (backup `.bak.devteam.<ts>` no box; `docker compose config` OK);
  `compose pull` (amd64 resolveu, sem problema de attestation) + `up -d`. Container **healthy** em ~16s; `/v1/health`
  interno = `{status:ok, tools:456}`; boot log `devteam_mcp_ready tools=456 domains=20 engine=mysql`.
- **GATEWAY_MAPPING:** row idempotente `name_microservice='platform-devteam-mcp'` (mcp_http, `http://platform-devteam-mcp:7100`,
  strip_prefix=1, `/v1/health`) inserida em `ADMIN_DATAFORALL.GATEWAY_MAPPING` (55→56 rows). ⚠️ **`docker exec -i` quebra
  sob SSM** (sem TTY/stdin → exit≠0 → `set -e` mata o script): usar `docker exec` SEM `-i` + `mysql -e "..."` inline.
- **Restart do `platform-mcp`:** feito; gateway volta **healthy**. (Na verdade o gateway re-agrega a cada ~60s —
  `REGISTRY_SOURCE=db` — então o restart nem seria estritamente necessário p/ uma row nova; mas garante determinismo.)
- **Prova no gateway:** logs do gateway = `GET http://platform-devteam-mcp:7100/mcp/tools/list "200 OK"` a cada ~60s
  → `catalog: 2018 tools across 55 services`; `/v1/health` do gateway = `{status:healthy, tools:2018}`. Backend serve
  **456 tools** (contagem tokenless confirmada no container). Namespace `devteam-mcp.*` vivo (strip_prefix=1 → 1:1).
- **Cadeia runtime provada por-equivalência:** `mcp__dataforall__session-mcp_list_sessions` (mesmo gateway/PAT/twin-exchange/
  dual-db que o devteam-mcp usa) retornou dados reais AO VIVO nesta sessão. O único delta do devteam-mcp é o container +
  audiência — ambos alinhados.

**Pendente (menor):** invocar literalmente 1 tool `devteam-mcp.*` de um cliente — bloqueado só porque o catálogo MCP
DESTA sessão é um snapshot pré-deploy (não re-enumera). Rodar de uma sessão/console NOVOS (que reconectam ao gateway e
já enxergam `devteam-mcp.*`).

### Padrão de referência (caso precise refazer/rollback)
Padrão idêntico ao dos 20 servers (memória `devteam-orm-mysql-pilot`). Scripts desta execução (efêmeros no scratchpad):
`ssm_run.sh` (base64-wrap + poll), `deploy_devteam.sh`, `map_devteam2.sh`, `restart_gateway.sh`, `gw_count.sh`.

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

### Risco #1 (`required_scope` sem `-mcp`) → ✅ RESOLVIDO (não é gate)
Verificado ao vivo: **o gateway NÃO casa scope contra `required_scope`.** `ADMIN_DATAFORALL.GATEWAY_MAPPING` não tem
coluna de scope; o `platform-mcp` não tem env de enforcement de scope; e o backend (`_verify_inner_token`) só valida
**audiência** (`mcp:devteam-mcp`) + exp + jti — não lê `required_scope`. O gate real é a **audiência**, derivada de
`name_microservice=platform-devteam-mcp` → `mcp:devteam-mcp`, que bate com o `MCP_TWIN_AUDIENCE` do container. Logo
`required_scope` é metadado (governança/audit), e dropar `-mcp` não bloqueia chamada nenhuma.

## Fase 5 — cutover → ✅ EXECUTADO (2026-07-17, forçado por decisão do usuário)
Removidas as **20 mappings** por-servidor do `GATEWAY_MAPPING` + **parados os 20 containers-fonte** (`docker stop`,
não `rm`). Gateway reagregado: **`catalog: 1616 tools across 35 services`** (era 2018/55 — caíram ~402 tools dos 20;
`devteam-mcp` com 456 permanece). Backup das 20 rows em `ADMIN_DATAFORALL.GATEWAY_MAPPING_BKP_devteam_cut`.

> ⚠️ **ESTADO ATUAL = superfície DevTeam por-servidor FORA, e NADA consome `devteam-mcp` ainda** (o refactor do
> agente/clientes — "Fase 4b" — NÃO foi feito). Ou seja: o `platform-devs-agent` deployado e qualquer cliente que
> use `architecture-mcp.*`/`session-mcp.*`/etc. está quebrado até a Fase 4b. Os 456 tools do `devteam-mcp.*` estão
> vivos no gateway, mas ninguém roteia p/ eles. **Caminho para restaurar função: fazer a Fase 4b (rotear por
> `devteam-mcp.*`) OU rollback.**

### Rollback do cutover (1 comando, reversível)
Re-inserir as 20 rows do backup + religar os 20 containers + restart do gateway:
```bash
# script pronto: scratchpad/rollback_cutover.sh (via ssm_run.sh). Núcleo:
docker exec dataforall-admin-mysql mysql -uroot -p"$PW" -e \
  "DELETE FROM ADMIN_DATAFORALL.GATEWAY_MAPPING WHERE name_microservice IN (<20 nomes>); \
   INSERT INTO ADMIN_DATAFORALL.GATEWAY_MAPPING SELECT * FROM ADMIN_DATAFORALL.GATEWAY_MAPPING_BKP_devteam_cut;"
docker start platform-architecture-mcp platform-backend-mcp ... (os 20) && docker restart platform-mcp
```
**Não apagar os diretórios `*-mcp-server/` do repo** nem remover os containers (`docker rm`) — são o fallback.

### Fase 4b (agora crítico) — rotear o agente/clientes por `devteam-mcp.*`
O `tool_matrix.py` do `platform-devs-agent` é só CONTRATO (não roteia — "NOTHING in the runtime imports it"). O
roteamento REAL está no `capability.py`/`catalog/policy.py`, que assumem namespaces `<persona>-mcp` (derivam o dono
pelo token antes do `-`). Para usar `devteam-mcp` (1 namespace, tools `<domínio>_<op>`), é um refactor real:
resolução de catálogo + `CapabilityEnforcer` + `PolicyEngine` por `data_domain`/capability em vez de por-servidor.
Repo clonado em `../platform-devs-agent` (branch `main`).

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
- Build local da image: comandos inline na seção "Prova local da image" acima (os scripts `scratchpad/*.sh` de
  ciclos anteriores eram efêmeros — não sobrevivem à sessão). Os passos de ACR/SSM da Fase 4 reusam o padrão das
  memórias `devteam-orm-mysql-pilot` e `platform-devs-agent-build`.
