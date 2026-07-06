# HANDOFF — Ambiente Enxuto DataForAll (HML)

> **Objetivo deste documento:** dar a quem assumir uma visão COMPLETA e acionável do
> ambiente enxuto — o que está no ar, o que está bloqueado, como operar, e os próximos
> passos com detalhe suficiente para continuar sem contexto oral.
>
> **Data:** 2026-07-06. **Ambiente:** 1 EC2 `t3.xlarge` Ubuntu 22.04, `us-east-1`,
> Cloudflare Tunnel (sem ingress público), acesso só por SSM. Conta AWS `011756140303`.
>
> **Documentos irmãos (leia junto):**
> - [bring-up-errors-and-fixes.md](bring-up-errors-and-fixes.md) — TODOS os erros com evidência/causa/correção (seções A–M). É a fonte canônica dos "porquês".
> - [environment-variables.md](environment-variables.md) — inventário de variáveis (mascaradas) + roster §5.0 + bloco por serviço.
> - [bring-up-from-scratch.md](bring-up-from-scratch.md) — guia operacional passo-a-passo (Terraform → infra → serviços → validação).
> - [local-db-access-ssm.md](local-db-access-ssm.md) — acesso aos DBs via SSM port-forward.

---

## 1. Estado atual (2026-07-06)

- **50 containers no ar** (2026-07-06: +2 sidecars do produto sales, +governance-mcp, +iceberg-mcp). ~24 serviços de aplicação healthy + data tier + observabilidade.
- **Front-door `platform-mcp`: 1043 tools / 27 serviços** (era 772/24; +crm/sales-partners/iceberg/governance-mcp). **platform-mcp foi patchado** (auth-por-backend via `additional_info.apiKey` — governance passou de 401→200). Login e2e **200**.
- **2 tenants** no `ADMIN_DATAFORALL.PLATFORMS`: `dataforall` (app.dataforall.tech) e `sales` (sales.dataforall.tech).
- **Recursos:** RAM 15Gi (≈8.3Gi usados, 6.7Gi disp.); disco root 18%, `/data` (EBS 100G) **76%** — **monitorar** (builds futuros + Trino/JVM apertam).

### 1.1 Serviços NO AR (healthy)

| # | Serviço | API | MCP | Tenant/DB | Notas-chave |
|---|---|---|---|---|---|
| 1 | dataforall-frontend | :8080 (nginx SPA) | — | — | borda do Tunnel (app.dataforall.tech) |
| 2 | platform-api-gateway | :9999 | ✅ :7100 | lê ADMIN | resolve tenant por Host (DomainTenantMiddleware) |
| 3 | platform-mcp | 127.0.0.1:8090 | (é o front-door) | lê ADMIN | agrega 772 tools de 24 serviços |
| 4 | platform-auth | :8000 | ✅ sse :28000 | mysql | assina JWT RS256; JWKS |
| 5 | platform-admin | :8000 | ✅ :7100 (v1) | mysql | IAM/usuários; twin exchange |
| 6 | platform-governance | :8000 | ✗ (mcp Exited — build quebrado) | mysql | ENV_PROFILE=hml |
| 7 | platform-notification | :8000 | ⚠️ mcp unhealthy (path 404 — K3) | mysql | Kafka OFF |
| 8 | platform-cdc | :8000 | ✅ :28000 | mysql | Kafka/coordinator OFF |
| 9 | platform-connectors | :8000 | ✅ :28000 (235 tools) | mysql | Fernet + OAUTH/WEBHOOK/FILE_PROXY secrets |
| 10 | platform-analytics | :8000 | ✅ :7100 (117 tools) | mysql | BI |
| 11 | platform-communication | :8000 | ✅ :7100 (65 tools) | mysql | K5/K6 resolvidos (sessão paralela) |
| 12 | platform-ml | :8000 | ✅ :7104 (71 tools) | mysql | **imagem enxuta (pull)**; alembic-inject; notif OFF (L1–L5) |
| 13 | platform-agents-factory | :8000 | ✅ :7130 (10 tools) | mysql | LLM keys lazy |
| 14 | platform-monitor | :8000 | ✅ :28000 (23 tools) | mysql | health :9090; migrations SQL puro (K7 vizinho) |
| 15 | platform-iceberg | :8018 | ⚠️ mcp NÃO no ar (repo corrigido, deploy pendente) | JsonStore | **lakehouse**: +minio+polaris+trino (M1–M4); SQL validado |
| 16 | platform-scheduler | :8000 | ✅ :7106 (21 tools) | **mysql via PLATFORMS** | JWT expire<=30; MCP bind-mount (K7) |
| 17 | platform-dai | :5003 | ✅ :7120 (46 tools) | mysql | orquestrador de agentes IA; DOCS_ENABLED=true p/ MCP (K8) |
| 18 | platform-db-vector | :5004 | ✗ (não em develop) | **pgvector dedicado** | RAG; `dbvec-postgres`; embeddings OpenAI (K9) |
| 19 | **platform-crm** | :8000 | ✅ :7100 (240 tools, mcp) | **tenant `sales`** | 75 tabelas `crm*`; MCP mora em `mcp/` (contexto `mcp`, 4 bugs — K10) |
| 20 | **platform-sales-partners** | :8000 | ✅ :7107 (mcp) | tenant `sales` | comissões/parceiros; **migrado** (rev 001→008, schema `sales`=89 tbls) |

### 1.2 Serviços BLOQUEADOS / PENDENTES

| Serviço | Situação | Detalhe / próximo passo |
|---|---|---|
| **platform-marketing** | ⏳ boot travado | Validadores hml exigem **TLS interno** (https S2S + `DB_SSLMODE=require`); o pool DB pendura no handshake TLS. Compose pronto em `deploy/services/platform-marketing/`. Precisa de TLS interno OU relaxar os validadores hml no repo. Container parado. |
| **platform-crm-agent** | ⏳ build falha | `pip install` erro (exit 1) — investigar detalhe (`/var/log/build-platform-crm-agent.log`). MCP é stdio/on-demand (não HTTP). MySQL viável. |
| **platform-marketing-agent** | ⏳ build falha | Dockerfile faz `COPY /tests` mas o dir não está no contexto (**bug de Dockerfile no repo**). MCP stdio. MySQL viável. |
| **platform-sales** | ⏳ pending | **postgres-only** (força `DB_ENGINE=postgresql`, asyncpg, `ON CONFLICT`/`BIGSERIAL`/`$1`). Não roda em MySQL sem reescrita. Decisão do usuário: adiar. |
| **platform-pipeline** | ⏳ aguardar | decisão do usuário (não subir por ora) |
| **platform-security** | ⏳ aguardar | decisão do usuário (repo não clonado local) |
| **platform-datalake / -docextract / -flow** | ⏳ build falha | bugs de Dockerfile no repo (git+ssh sem openssh / sem git / COPY .sh inexistente) — tarefa `task_d614b502` |

### 1.3 Anomalias de MCP a resolver

- **platform-governance-mcp**: ✅ **RESOLVIDO — agregando 8 tools** (`Up healthy`, :7103). Foram 3 bugs: (1) contexto de build (MCP em `mcp/src/server/`); (2) **dep cross-package** — `mcp_server.py` importa `platform_governance.policy` (policy lib na RAIZ) → fix: build **contexto RAIZ** instalando OS 2 pacotes (`pip install .` + `pip install ./mcp`; deps leves); (3) **401 no list** — `mcp_server.py:252` exige Bearer (Twin PEP, `MCP_GOVERNANCE_SERVICE_TOKEN`=INTERNAL_API_TOKEN) → resolvido **patchando o platform-mcp** (`load_from_db` lê `additional_info.apiKey` → aggregator manda `Authorization: Bearer`) + `additional_info={"apiKey":INTERNAL_API_TOKEN}` na row. governance passou de **401→200** (1035→1043 tools). **PRs pendentes:** governance-mcp (Dockerfile custom, mesmo padrão do #22) e **platform-mcp-gateway [PR #9](https://github.com/dataforalltech/platform-mcp-gateway/pull/9)** (patch do registry).
- **platform-notification-mcp**: **é um MCP de transporte SSE**, não HTTP — `CMD uvicorn notification_mcp.server.mcp_server:app :7100`, e o server é um **Starlette** com `Route("/sse", handle_sse)` + `Mount("/messages/", sse.handle_post_message)`. Por isso `/mcp/tools/list` dá 404 (não existe). Registrar como `sse` (path `/sse`) como o `auth-mcp` — MAS a **agregação SSE no front-door está pendente** (mesma nota do auth-mcp), então não agrega tools até o platform-mcp suportar SSE. Bloqueio = capability do front-door, não path.
- **platform-iceberg-mcp**: ✅ **NO AR + AGREGANDO 13 tools**. Buildado (`build-service.sh platform-iceberg-mcp platform-iceberg develop mcp/Dockerfile .` — contexto **RAIZ**; o Dockerfile faz `COPY mcp/requirements.txt`+`COPY app/iceberg_mcp/`). CMD `python -m iceberg_mcp.server` :7104. Env (lido via `os.environ`, sem settings.py): `ICEBERG_BASE_URL=http://platform-iceberg:8018`, `ICEBERG_INTERNAL_URL`, `ICEBERG_HEALTH_URL`, `ICEBERG_INTERNAL_TOKEN`/`MCP_SERVICE_TOKEN`=INTERNAL_API_TOKEN, `ICEBERG_MCP_TWIN_ENFORCE=false`. Só precisa da `platform-local`. Subido via `docker run` (teste) — compose reproduzível em **`deploy/services/platform-iceberg/docker-compose.mcp.yml`** (novo). Registro já existia (:7104).

---

## 2. Arquitetura

### 2.1 Rede / borda
- **Cloudflare Tunnel** roteia `*.dataforall.tech` (wildcard DNS) → `localhost:8080` na EC2 → **nginx (borda de frontend)** → SPA; `/api` e `/ws` → gateway (`host.docker.internal:9999`), **preservando o Host** (o gateway resolve o tenant pelo domínio).
- **Sem ingress público** (Security Group sem entrada). Todo acesso administrativo por **SSM**.
- Rede docker interna compartilhada: **`platform-local`** (external). O lakehouse iceberg tem rede dedicada `iceberg-net`; o db-vector usa `dbvec-postgres` na `platform-local`.

### 2.2 Multi-tenant por domínio (D7)
- `ADMIN_DATAFORALL.PLATFORMS` mapeia **`domain` → `tenant_id`** + `db_engine/db_host/...`. O gateway (`DomainTenantMiddleware`) resolve o tenant pelo `Host`. Só `/api/internal/*` bypassa a resolução.
- Tenant DB nomeado pelo `tenant_id` (ex.: `dataforall`, `sales`). Migrations por tenant (`alembic -x tenant_id=<t> -x db_engine=mysql -x db_host=tenant-mysql ...`).
- **Serviços que resolvem o tenant DB do PLATFORMS** (ex.: scheduler, crm) usam o que estiver na linha do tenant. Os demais usam `DB_*` do compose direto.

### 2.3 Data tier
- **admin-mysql** (`ADMIN_DATAFORALL`: PLATFORMS, GATEWAY_MAPPING) — sempre MySQL.
- **tenant-mysql** (DBs por tenant: `dataforall`, `sales`, + `platform_auth`).
- **tenant-postgres** (`postgres:16-alpine`, hoje sem uso ativo — serviços postgres não subiram).
- **dbvec-postgres** (`pgvector/pgvector:pg16`) — dedicado ao db-vector.
- **redis**, **kafka** (desligado nos serviços), **vault** (dev), **prometheus/grafana/tempo/otel**.

### 2.4 Delivery / build
- **Build:** `deploy/build/build-service.sh <image> <repo> <branch> [dockerfile=Dockerfile] [context=.]` — clona `github.com/dataforalltech/<repo>@<branch>`, builda com `--secret id=github_token` (libs privadas), push `d4all.azurecr.io/dataforall/3.0/<image>:latest`+`:<sha>`.
- **Arquivos → S3 → box:** `aws s3 sync deploy/ s3://dataforall-hml-backups-011756140303/deploy --exclude ".env" --exclude "secrets/*"`; a EC2 puxa e roda via **SSM AWS-RunShellScript**.
- **Execução:** composes por serviço em `deploy/services/<svc>/docker-compose.yml`, `--env-file /opt/dataforall/deploy/.env`, rede `platform-local`.

---

## 3. FRONTENDS & SUBDOMÍNIOS (arquitetura-alvo)

> **NOVO (decisão do usuário 2026-07-06):** a plataforma terá **múltiplos frontends**, cada um
> num subdomínio próprio, todos atrás do wildcard `*.dataforall.tech` (Tunnel → nginx por Host).
> **Manter o atual + o de sales; +2 novos.**

| Subdomínio | Frontend (repo) | Backends principais | Tenant | Status |
|---|---|---|---|---|
| `app.dataforall.tech` (atual) | `platform-dataforall-frontend` (product-dataforall) | plataforma toda | `dataforall` | ✅ no ar |
| `sales.dataforall.tech` | **`dataforall-sales-frontend`** (branch **`main`**) | platform-crm, platform-sales-partners | **`sales`** | backend crm+sales-partners MCP no ar; borda **NÃO** dedicada (catch-all vaza o SPA do app); repo é **Vite puro SEM Dockerfile** — falta scaffolding+build+rota |
| `partner.dataforall.tech` | **`platform-sales-partners-frontend`** (branch **`develop`**) | platform-sales-partners | a definir (tenant) | idem: Vite puro sem Dockerfile; precisa scaffolding+build+rota + linha no PLATFORMS |
| `admin.dataforall.tech` | (3º frontend novo — a definir/clonar) | platform-admin | a definir | ⏳ planejado |
| `platform.dataforall.tech` | (provável = o "atual" renomeado, a confirmar) | plataforma toda | `dataforall` | ⏳ planejado |

> ⚠️ **A confirmar com o usuário:** o mapeamento exato dos 4 subdomínios ↔ frontends ↔ tenants.
> O usuário disse "manter esse (sales) e o atual, e teremos mais 2 frontends", listando
> `partner`, `admin`, `platform`. Interpretação provável: `platform.dataforall.tech` = o frontend
> atual (hoje em `app`), e `partner`/`admin` = os 2 novos. **Cada subdomínio novo precisa de:**
> (1) linha no `PLATFORMS` (`domain` → `tenant_id`), (2) `server_block` no nginx da borda servindo o
> SPA daquele produto + `/api`→gateway, (3) build do SPA. O wildcard DNS/Tunnel já cobre qualquer subdomínio.

### 3.1 Como subir um frontend novo (padrão)

> **Descoberto 2026-07-06:** o app (`platform-dataforall-frontend`, branch `main`) é buildado por um **Dockerfile multi-stage** (node build → `nginxinc/nginx-unprivileged:1.27-alpine` :8080) com `docker/nginx.conf` + `docker/30-runtime-env.sh` (gera `env.js` em runtime; envsubst só de `INTERNAL_TOKEN`/`GATEWAY_UPSTREAM`). Os repos `dataforall-sales-frontend` e `platform-sales-partners-frontend` são **Vite puros SEM esse scaffolding** — para buildá-los como imagem, **portar o `Dockerfile` + `docker/` do app** p/ cada um (ou buildar com um Dockerfile genérico à parte). Depois, a **borda** precisa virar roteadora por `server_name` (hoje é `server_name _` catch-all servindo só o app). Nomes de imagem sugeridos: `platform-sales-frontend`, `platform-sales-partners-frontend`.

1. Clonar o repo do frontend, `npm ci && npm run build` (Vite → `dist/`).
2. Servir o `dist/` num container nginx (ou um bloco no nginx da borda) que:
   - responde ao `server_name <sub>.dataforall.tech`,
   - serve o SPA (fallback `index.html`),
   - faz proxy de `/api` e `/ws` → `host.docker.internal:9999` (gateway) **preservando o Host**.
3. Criar a linha no `PLATFORMS` (`domain=<sub>.dataforall.tech` → `tenant_id`) e provisionar o tenant DB, se for tenant novo.
4. Anti-scraping do nginx pode bloquear `curl` — testar com UA de browser (ver runbook D1).

---

## 4. Tenants

| tenant_id | domain | engine | DB(s) | Notas |
|---|---|---|---|---|
| `dataforall` | app.dataforall.tech | mysql | `dataforall` (tenant-mysql) | superadmin `admin@dataforall.tech` / `••••` (senha de teste definida no `onboard-tenant.sh` — trocar em uso real) |
| `sales` | sales.dataforall.tech | mysql | `sales` (tenant-mysql) | criado nesta rodada; crm migrado (75 tabelas); **sales-partners AINDA sem migrar** |

**Provisionar um tenant novo:**
1. `INSERT` no `ADMIN_DATAFORALL.PLATFORMS` com **todas as colunas NOT-NULL** (`tenant_id, domain, name, db_engine, db_host, db_port, db_user, db_password, internal_token, internal_port, url` + `active=1`). *(Gotcha: o INSERT falha silenciosamente se faltar coluna obrigatória — foi o que aconteceu com `sales` na 1ª tentativa.)*
2. `CREATE DATABASE <tenant> CHARACTER SET utf8mb4` no tenant-mysql.
3. Rodar as migrations de cada serviço para o tenant: `docker exec <svc> alembic -x tenant_id=<t> -x db_engine=mysql -x db_host=tenant-mysql -x db_port=3306 -x db_user=root -x db_password=<pw> -x db_name=<t> upgrade head`.

---

## 5. Segredos & acesso

- **`.env` on-box** (`/opt/dataforall/deploy/.env`, chmod 600) — gerado on-box; **nunca no git nem no S3** (sempre `--exclude ".env"`). Chaves: `MYSQL_ROOT_PASSWORD`, `POSTGRES_PASSWORD`, `REDIS_PASSWORD`, `INTERNAL_API_TOKEN`, `JWT_SECRET_KEY`, `CREDENTIAL_ENCRYPTION_KEY`, `OAUTH_STATE_SECRET`/`WEBHOOK_SECRET`/`FILE_PROXY_SECRET` (connectors), `PII_PSEUDONYMISATION_KEY`+`MCP_SERVICE_TOKEN` (marketing), `ICEBERG_*`, `DBVEC_PG_PASSWORD`, `OPENAI_API_KEY` (db-vector, do SSM). Inventário mascarado em [environment-variables.md](environment-variables.md).
- **SSM Parameter Store** (`/dataforall-hml/*`, cifrado KMS): ACR user/pass, GitHub token/org, JWT RSA key, Cloudflare tunnel token, **`/dataforall-hml/openai/api-key`** (novo — chave OpenAI do db-vector).
- **Acesso à EC2:** `aws ssm start-session --target i-002379444ffb89c10 --region us-east-1`.
- **Acesso aos DBs (IDE):** SSM port-forward — ver [local-db-access-ssm.md](local-db-access-ssm.md).
- **Windows local (operador):** `PYTHONIOENCODING=utf-8 PYTHONUTF8=1` antes de `aws`; ler env User/Machine via `powershell [Environment]::GetEnvironmentVariable('NOME','User'|'Machine')`.

---

## 6. Aprendizados críticos (resumo — detalhe no runbook de erros)

- **Disco/reboot (B9):** o **containerd guarda as IMAGENS no root de 40G** (o `data-root=/data/docker` NÃO move isso); e os **device names NVMe trocam no reboot**. Já bakado no `bringup-infra.sh` (containerd→/data via symlink + fstab por UUID). **TODO: replicar no user_data do Terraform.**
- **MySQL vs postgres-only:** vários serviços têm migrations **dialect-aware** (rodam em mysql); alguns têm sintaxe **postgres-only** que quebra (ml `IF NOT EXISTS`, db-vector, platform-sales). Sempre checar antes de forçar mysql.
- **MCPs variam MUITO:** imagem própria HTTP (`mcp/Dockerfile` ou `Dockerfile.mcp`, portas 7100/7104/7106/7107/7120/28000, estilos `mcp`/`v1`/`sse`) vs **stdio/on-demand** (agentes crm-agent/marketing-agent — não são sidecars HTTP registráveis). Alguns Dockerfiles **esquecem `COPY mcp/`** (scheduler, iceberg) ou **deps** (dai faltava PyJWT). Registro via `deploy/seed/register-mcp-backends.sh`.
- **Validadores prod-parity em hml:** alguns serviços exigem RS256, JWKS, `JWT_ACCESS_TOKEN_EXPIRE_MINUTES<=30` (scheduler), **https S2S + DB TLS** (marketing — bloqueou). `ENVIRONMENT=staging` costuma ser tratado como prod-like.
- **Builds:** sequenciais por repo (paralelo colide no clone — J5); confira o **contexto** do `mcp/Dockerfile` (J6); tags de libs privadas às vezes não existem (db-vector `docextract-lib@v0.1.1`→`v0.1.0`).

---

## 7. PRÓXIMOS PASSOS (ordenados, acionáveis)

### A. Fechar o produto sales (escolha atual do usuário: "completar os 2 + frontend")
1. ✅ **FEITO — crm-mcp e sales-partners-mcp** buildados, no ar (healthy) e registrados no front-door (1022 tools/26 services). sales-partners-mcp limpo; crm-mcp exigiu **4 correções de Dockerfile/pyproject + config** — ver runbook **K10**. ⚠️ crm-mcp foi buildado da **box** (correções ainda não commitadas no repo `platform-crm`) — ver **§7.D item 11b** (PR pendente) p/ reprodutibilidade.
2. ✅ **FEITO — sales-partners migrado no tenant `sales`** (`alembic upgrade head`, rev 001→008; schema `sales` foi p/ 89 tabelas).
3. **Borda `sales.dataforall.tech` (e `partner`):** ⚠️ **cada subdomínio é um FRONTEND DISTINTO** (SPA próprio), não o mesmo SPA multi-tenant. Hoje o nginx é `server_name _` (catch-all) servindo **só a imagem do app** (`platform-dataforall-frontend`, SPA Vite embutido) → `sales`/`partner` **vazam o SPA do app** (errado). Falta: (a) **buildar 1 imagem por frontend** (`platform-sales-frontend`, `platform-partner-frontend`) do repo de cada um, mesmo padrão do app (`build-service.sh <img> <repo> <branch> Dockerfile .` — nginx + SPA embutido); (b) **rotear por `server_name`** na borda (Host → SPA correto; `/api`/`/ws`→gateway igual p/ todos, que resolve tenant por Host). Repos dos SPAs de sales/partner **não estão na box** e os nomes precisam ser confirmados. A linha `sales` no PLATFORMS já existe; `partner` precisa de linha + tenant se for tenant novo.

### B. Frontends adicionais
4. Confirmar com o usuário o mapa subdomínio↔frontend↔tenant (§3). Subir `partner.`, `admin.`, `platform.` conforme (§3.1), criando tenants/PLATFORMS se necessário.

### C. Destravar os bloqueados (se/quando priorizado)
5. **crm-agent / marketing-agent builds:** ler `/var/log/build-platform-*-agent.log`; crm-agent = erro pip (provável tag de lib); marketing-agent = `COPY /tests` inexistente (fix de Dockerfile no repo). Padrão db-vector/dai: patch + rebuild + (commit sob aprovação).
6. **marketing (TLS):** decidir entre (a) TLS interno no data tier, ou (b) relaxar os validadores hml do marketing no repo (https S2S + DB_SSLMODE). Sem isso o boot pendura.
7. **platform-sales:** postgres nativo (exceção) OU reescrita mysql. Adiado.
8. **pipeline / security:** aguardando decisão do usuário.

### D. Higiene do que já subiu
9. ✅ **FEITO — iceberg-mcp** no ar + agregando **13 tools** (compose `docker-compose.mcp.yml`).
10. ✅ **FEITO — governance-mcp agregando (8 tools)** via patch do platform-mcp (auth-por-backend, [PR #9](https://github.com/dataforalltech/platform-mcp-gateway/pull/9)) + `additional_info.apiKey`. **notification-mcp** = MCP **SSE**; a agregação SSE JÁ existe no aggregator (`sse_adapter`), mas o handshake com o `/sse` do notification **falha** (erro vazio) — precisa debugar o handshake MCP-SSE (talvez exija auth/protocolo específico). O `auth-mcp` (também sse) é o outro caso. **PRs pendentes:** governance-mcp (Dockerfile) — o do platform-mcp (#9) já está aberto.
11. **Tarefas de repo em background** (verificar se fecharam com diff pronto): `task_d614b502` (4 Dockerfiles), `task_75f06d5a` (ml), `task_0a535f1a` (scheduler COPY mcp/), `task_e2851af5` (iceberg-mcp, encerrada).
11b. ✅ **FEITO — PR no repo `platform-crm`:** [PR #22](https://github.com/dataforalltech/platform-crm/pull/22) (branch `fix/crm-mcp-sidecar-build` → `develop`) com as correções do crm-mcp — `mcp/Dockerfile` (contexto `mcp`, `COPY src/`, `git`, secret `github_token`, `platform-core-lib@v0.3.0`) e `mcp/pyproject.toml` (`[tool.hatch.metadata] allow-direct-references=true`). Após merge: `build-service.sh platform-crm-mcp platform-crm develop mcp/Dockerfile mcp`. Detalhe: runbook **K10**.

### E. Reprodutibilidade / infra
12. Bakar o fix do containerd/fstab (B9) no **user_data do Terraform** (`compute.tf`), além do `bringup-infra.sh`.

---

## 8. Convenções desta operação (regras que valeram)

- **Papel:** nesta sessão foi autorizado **executar** (build/deploy) e **corrigir na raiz** os repos de serviço (ex.: dai, db-vector), commitando/pushando **sob aprovação por lote**. Segredos gerados on-box, nunca no git.
- **Branch:** buildar sempre de **`develop` atualizado** (`git checkout develop && git pull`); reset --hard pro origin quando divergente (com aprovação).
- **Documentar todo erro** com evidência/causa/correção no runbook de erros (para a VM subir limpa nas próximas).
- **platform-devs branch de trabalho:** `feat/terraform-lean-and-docs` **já foi mergeado no `develop`** (commit `141e318`); o `develop` está atualizado (não está mais atrás). Novo ciclo = **nova branch** a partir de `develop`. ⚠️ Sessões paralelas compartilharam o mesmo working tree e já causaram troca de branch/bagunça — preferir **worktrees isolados** ou uma sessão por vez.
