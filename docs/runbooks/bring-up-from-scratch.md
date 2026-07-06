# Subir o ambiente enxuto DO ZERO — guia operacional

> Índice único que liga **Terraform → infra → imagens → serviços → validação**,
> apontando os scripts e o runbook de erros. Ambiente: 1 EC2 (`t3.xlarge`,
> `us-east-1`) + Cloudflare Tunnel, sem porta pública. Conta AWS `011756140303`.
>
> Erros conhecidos (evidência/causa/correção): [bring-up-errors-and-fixes.md](bring-up-errors-and-fixes.md).
> Muitas correções já estão **bakadas** nos scripts abaixo — este guia é o caminho feliz.

---

## 0. Pré-requisitos (uma vez)

**Segredos no SSM Parameter Store** (`us-east-1`, cifrados com `alias/dataforall-hml`):
| Parâmetro | Conteúdo |
|---|---|
| `/dataforall-hml/acr/username` + `/acr/password` | credenciais do ACR (`d4all.azurecr.io`) |
| `/dataforall-hml/github/token` + `/github/org` | PAT do GitHub (libs privadas) + `dataforalltech` |
| `/dataforall-hml/platform-auth/jwt-private-key` | chave RSA de assinatura (ou backup em `s3://<bucket>/secrets/`) |

**Local (Windows):** `CLOUDFLARE_API_TOKEN` (token `platform-infra-dev`, com Tunnel Read/Write) no ambiente User.
Ao rodar `aws`/scripts no Git Bash: `export PYTHONIOENCODING=utf-8 PYTHONUTF8=1 MSYS_NO_PATHCONV=1` (ver B1/B3).

---

## 1. Infra AWS (Terraform)

```bash
cd platform-devs/terraform-lean
export CLOUDFLARE_API_TOKEN=$(powershell.exe -NoProfile -Command "[Environment]::GetEnvironmentVariable('CLOUDFLARE_API_TOKEN','User')" | tr -d '\r\n')
terraform init
terraform plan -out=tfplan     # ~28 recursos
terraform apply tfplan          # NAO usar -auto-approve (classifier bloqueia)
terraform output                # instance_id, public_ip, tunnel_id, bucket
```
Cria: EC2 (IMDSv2, user_data instala Docker+cloudflared, monta /data, swap), VPC/subnet/IGW,
SG **sem ingress**, IAM (kms:Decrypt, ssm:GetParameter em `/dataforall-hml/*`, s3), Cloudflare
Tunnel + DNS wildcard `*.dataforall.tech`, KMS, S3 backups, DLM.
> Gotchas: A2 (descrição ASCII), A3 (apex já existe), A4 (nome de bucket S3 global após destroy).

Acesso à EC2: `aws ssm start-session --target <instance_id> --region us-east-1` (sem SSH).

---

## 2. Infra em containers (data tier + Vault + observabilidade)

Suba o `deploy/` no S3 e rode o bring-up via SSM:
```bash
aws s3 sync platform-devs/deploy s3://<bucket>/deploy --exclude ".env" --exclude "secrets/*"
# na EC2 (via SSM RunShellScript):
bash terraform-lean/scripts/bringup-infra.sh
```
Faz: `data-root=/data/docker` (B6), rede `platform-local` (B5), gera `.env` on-box
(senhas fortes), `docker compose -f deploy/docker-compose.infra.yml up -d`.
Sobe: admin-mysql, tenant-mysql, tenant-postgres, redis, kafka, vault, prometheus,
grafana, tempo, otel. (MySQL 8.4 usa `--authentication-policy` — B7.)

> **NUNCA** rodar `aws s3 sync --delete` sem `--exclude ".env"` — apaga as senhas (C1).

---

## 3. Rebuild das imagens do ACR (recomendado)

As imagens `:latest` do ACR ficam **defasadas do código** (causa-raiz de vários bugs — F6/I).
Rebuilde do código atual:
```bash
# na EC2, por serviço (branch varia: auth=release/1.4.0, resto=develop):
bash deploy/build/build-service.sh platform-auth platform-auth release/1.4.0 Dockerfile .
bash deploy/build/build-service.sh platform-api-gateway platform-api-gateway develop Dockerfile .
# MCP: dockerfile e contexto variam por repo (K):
bash deploy/build/build-service.sh platform-api-gateway-mcp platform-api-gateway develop gateway_mcp/Dockerfile .
bash deploy/build/build-service.sh platform-auth-mcp platform-auth release/1.4.0 mcp/Dockerfile mcp
```
Clona `github.com/dataforalltech/<repo>`, builda com `--secret id=github_token`, push `:latest`+`:sha`.

---

## 4. Frontend (a BORDA do Tunnel)

```bash
bash deploy/frontend/bringup.sh   # login ACR + pull + up (nginx SPA na :8080)
```
O Cloudflare Tunnel roteia `*.dataforall.tech` → `localhost:8080` → nginx → SPA;
`/api` e `/ws` → gateway (host.docker.internal:9999), preservando o Host (tenancy).
Valide (UA de browser — o nginx bloqueia curl, D1):
`curl -A "Mozilla/5.0 Chrome/120" https://app.dataforall.tech/  → 200`

---

## 5. Serviços core + provisão do tenant

Suba API+MCP de cada core (compose por serviço em `deploy/services/<svc>/`):
```bash
# gateway (#2), auth (#3), admin (#5), governance (#4) — cada um:
cd deploy/services/<svc> && docker compose --env-file /opt/dataforall/deploy/.env up -d --no-build
```
Padrão de env (ver composes): `RUNTIME_ENV=local`, `ENV_PROFILE=local-hml` (governance usa `=hml`, K),
chave RSA compartilhada auth+admin em `secrets/jwt-auth.pem` (**chown 1000 + chmod 600**, F7),
URLs S2S **diretas** (nunca pelo gateway, F6).

Provisione o tenant (cria DB + migrations admin/auth/gov + superadmin):
```bash
bash deploy/seed/onboard-tenant.sh dataforall admin@dataforall.tech 'Dataforall@2026'
```
Aponte as rotas do gateway para os containers (o bootstrap usa localhost — E4):
```bash
for s in platform-auth platform-admin platform-governance; do bash deploy/seed/fix-gateway-route.sh $s 8000; done
```

---

## 6. Validar login e2e

```bash
curl -s -X POST https://app.dataforall.tech/api/v1/auth/login \
  -H "Content-Type: application/json" -H "X-Browser-Id: dev-001" \
  -A "Mozilla/5.0 Chrome/120" \
  -d '{"email":"admin@dataforall.tech","password":"Dataforall@2026"}'
# esperado: 200 + auth_token (JWT RS256), user superadmin, mfa_required:false
```
> Sem `X-Browser-Id` → 401 "Browser binding missing" (F10, esperado). Cadeia:
> Browser→CF→Tunnel→nginx→gateway(resolve tenant)→auth→admin(valida Argon2id)→auth(assina JWT)→200.

---

## 7. Demais serviços — receita por-serviço (1 a 1)

Padrão validado (auth/admin/governance/mcp/notification/connectors/analytics). Para cada `<svc>`:

1. **Mapear** os requisitos do repo antes: `ENV_PROFILE` que o validador exige
   (`local-hml` OU `hml==APP_ENV` — ver K), `DB_ENGINE` (mysql/postgres), health (porta+path),
   e **TODOS os segredos obrigatórios** — `grep -nE 'must be set|raise ValueError' app/core/config.py`
   no repo lista tudo de uma vez (evita restart-loop iterando; ver K4).
2. **Imagem** no ACR: `build-service.sh <svc> <svc> <branch> Dockerfile .` (API) e o MCP com o
   dockerfile/contexto do repo (varia: `mcp/Dockerfile` ctx `mcp`, `Dockerfile.mcp` ctx `.`, etc. — K).
3. **Compose** em `deploy/services/<svc>/docker-compose.yml` (copie um par pronto — connectors/analytics
   são bons modelos): tabela comum de env + os específicos/segredos do serviço.
4. **Subir + migrations + rota:**
   ```bash
   docker compose --env-file /opt/dataforall/deploy/.env up -d --no-build <svc>
   # migrations (se tiver estado): reusa o padrao do onboard
   docker exec -w /app <svc> sh -c "alembic -x tenant_id=dataforall -x db_host=tenant-mysql \
     -x db_port=3306 -x db_user=root -x db_password=<pw> -x db_name=dataforall upgrade head"
   bash deploy/seed/fix-gateway-route.sh <svc> 8000
   ```
   > Segredos novos obrigatórios → adicione ao `/opt/dataforall/deploy/.env` (gerar `openssl rand -hex 32`)
   > e documente em `environment-variables.md`.
5. **MCP:** suba o sidecar e registre no front-door: `deploy/seed/register-mcp-backends.sh` (ou um
   `INSERT` no `GATEWAY_MAPPING` com `kind=mcp_http`, `mcp_url`, o `tools_list_path` do sidecar) +
   `docker restart platform-mcp`. Confirme `catalog: N tools` crescer.

> **Engine postgres** (crm/finance/marketing/sales/scheduler): `DB_ENGINE=postgresql`,
> `DB_HOST=tenant-postgres`, `DB_PORT=5432`, `DB_USER=platform`, `DB_PASSWORD=${POSTGRES_PASSWORD}`.

---

## Acesso ao ambiente (HML)
| | |
|---|---|
| URL | `https://app.dataforall.tech` (SPA / login) |
| Usuário | `admin@dataforall.tech` (superadmin) |
| Senha | a definida no `onboard-tenant.sh` (padrão de teste `Dataforall@2026` — **trocar em uso real**) |
| Tenant | `dataforall` (resolvido pelo subdomínio via `PLATFORMS.domain=app.dataforall.tech`) |

Novo tenant/usuário: `onboard-tenant.sh <tenant_id> <email> <senha>` (cria DB + migrations + superadmin).
Acesso à EC2: `aws ssm start-session --target <instance_id> --region us-east-1`.
Acesso aos DBs no IDE: `terraform-lean/scripts/db-tunnel.ps1` (SSM port-forward — ver [local-db-access-ssm.md](local-db-access-ssm.md)).

## Referências
- **Erros** (A–K): [bring-up-errors-and-fixes.md](bring-up-errors-and-fixes.md)
- **Variáveis de ambiente** (inventário, senhas mascaradas): [environment-variables.md](environment-variables.md)
- **Acesso local aos DBs** (SSM port-forward): [local-db-access-ssm.md](local-db-access-ssm.md)
- **Arquitetura definitiva** (D1–D7): [../architecture/official-stack-and-architecture.md](../architecture/official-stack-and-architecture.md)
- **Playbook de produção (escala)**: [aws-production-deployment-playbook.md](aws-production-deployment-playbook.md)

## Estado atual (2026-07-06)
**9 APIs healthy:** frontend, gateway, auth, admin, governance, mcp, notification, connectors, analytics.
**6 MCP sidecars healthy** (gateway/auth/admin/notification/connectors/analytics); o **platform-mcp
(front-door) agrega 592 tools**. **Login e2e 200.** Pendências: `governance-mcp` (defeito de build no
repo — K1), `notification-mcp`/`auth-mcp` (agregação de tools — path/SSE, K3), e os demais ~20 serviços
(rebuild + subida 1 a 1). Ver roster completo em [environment-variables.md](environment-variables.md) §5.0.
