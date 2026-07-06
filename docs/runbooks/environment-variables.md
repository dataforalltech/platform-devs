# Inventário de variáveis de ambiente — ambiente enxuto

> Todas as variáveis configuradas para subir o ambiente enxuto, por escopo.
> **Senhas/tokens estão mascarados** (`••••`); a coluna "Origem" diz de onde vem o valor real.
> Valores concretos vivem no `.env` on-box (chmod 600), no SSM (SecureString) ou no
> ambiente Windows local — **nunca** no git.

Legenda de origem: **on-box** = gerado na EC2 no bring-up (`.env`); **SSM** = AWS SSM
Parameter Store (cifrado KMS); **local** = ambiente Windows do operador; **fixo** = valor
não-secreto definido no compose/terraform.

---

## 1. Segredos do `.env` on-box (`/opt/dataforall/deploy/.env`, chmod 600)

Gerados na 1ª subida (`bringup-infra.sh` + bring-ups dos serviços). Recuperáveis dos
containers se o arquivo sumir (ver runbook de erros C1).

| Variável | Valor | Origem | Usado por |
|---|---|---|---|
| `MYSQL_ROOT_PASSWORD` | `••••` (32 chars) | on-box | admin-mysql, tenant-mysql, todos os serviços (ADMIN_DB/DB) |
| `POSTGRES_PASSWORD` | `••••` (32) | on-box | tenant-postgres (serviços com DB_ENGINE=postgresql) |
| `REDIS_PASSWORD` | `••••` (32) | on-box | redis; RATE_LIMIT/REDIS_URL dos serviços |
| `VAULT_ROOT_TOKEN` | `••••` (hex) | on-box | vault (dev), seed da chave RSA |
| `GRAFANA_ADMIN_PASSWORD` | `••••` (24) | on-box | grafana |
| `INTERNAL_API_TOKEN` | `••••` (hex 32) | on-box | token S2S compartilhado (todos os serviços + MCPs) |
| `HEALTH_MONITORING_TOKEN` | `••••` (hex 32) | on-box | gateway (probe de health autenticado) |
| `JWT_SECRET_KEY` | `••••` (hex 40) | on-box | auth/admin/governance/notification (service tokens HS/valida) |
| `CREDENTIAL_ENCRYPTION_KEY` | `••••` (Fernet 44) | on-box | admin/governance/notification/connectors (cifra credenciais) |
| `OAUTH_STATE_SECRET` | `••••` (hex 32) | on-box | connectors (assina state OAuth) |
| `WEBHOOK_SECRET` | `••••` (hex 32) | on-box | connectors (assina tokens de webhook PIX/PSP) |
| `FILE_PROXY_SECRET` | `••••` (hex 32) | on-box | connectors (assina URLs do file proxy) |

---

## 2. SSM Parameter Store (`us-east-1`, cifrado `alias/dataforall-hml`)

| Parâmetro | Valor | Tipo | Origem |
|---|---|---|---|
| `/dataforall-hml/acr/username` | `agents-platform-cicd` | String | local (`DEPLOY_ACR_USERNAME`) |
| `/dataforall-hml/acr/password` | `••••` | SecureString | local (`DEPLOY_ACR_PASSWORD`) |
| `/dataforall-hml/github/token` | `••••` (PAT) | SecureString | local (`DEPLOY_GITHUB_TOKEN`) |
| `/dataforall-hml/github/org` | `dataforalltech` | String | local (`DEPLOY_GITHUB_ORG`) |
| `/dataforall-hml/platform-auth/jwt-private-key` | `••••` (RSA PEM) | SecureString | on-box (gerada; backup em S3) |
| `/dataforall-hml/cloudflare-tunnel-token` | `••••` | SecureString | terraform (tunnel) |

Chave RSA também em `s3://dataforall-hml-backups-011756140303/secrets/platform-auth-jwt.pem`
e no Vault `kv/dataforall/platform-auth/jwt_private_key`. Montada nos containers auth/admin
em `/run/secrets/jwt_key.pem` (chown 1000 + 600).

---

## 3. Ambiente Windows local (operador)

| Variável | Valor | Uso |
|---|---|---|
| `CLOUDFLARE_API_TOKEN` | `••••` (token `platform-infra-dev`) | terraform (tunnel/DNS) |
| `DEPLOY_ACR_USERNAME` / `DEPLOY_ACR_PASSWORD` | `agents-platform-cicd` / `••••` | fonte do SSM ACR |
| `DEPLOY_GITHUB_TOKEN` / `DEPLOY_GITHUB_ORG` | `••••` / `dataforalltech` | fonte do SSM GitHub |

---

## 4. Terraform (`terraform-lean`, `terraform.tfvars` — gitignored)

| Variável | Valor | Tipo |
|---|---|---|
| `region` | `us-east-1` | fixo |
| `az` | `us-east-1a` | fixo |
| `domain` | `dataforall.tech` | fixo |
| `cloudflare_zone_id` | `2a74d4c384c07781196ad2f84db55251` | fixo |
| `cloudflare_account_id` | `8a10daf8154467b3a720120b7ee65ed4` | fixo |
| `instance_type` | `t3.xlarge` | fixo |
| `owner` | `platform-dataforall-tests` | fixo (tag) |
| `cost_center` | `dataforall-tests` | fixo (tag) |
| `data_gib` | `100` | fixo |

Recursos gerados: EC2 `i-002379444ffb89c10`, bucket `dataforall-hml-backups-011756140303`,
tunnel `17ea08ca-...`, KMS `alias/dataforall-hml`.

---

## 5. Env por serviço (composes em `deploy/services/<svc>/`)

### 5.0 Roster completo (todos os serviços — subidos e pendentes)

Status: ✅ no ar · ⬜ pendente · img✅/img✗ = imagem `:latest` rebuildada no ACR (ou falhou).
Engine define `DB_HOST`/`DB_PORT`/`DB_USER` (mysql→`tenant-mysql:3306` root; postgres→`tenant-postgres:5432` platform).
Pendentes seguem a **tabela comum (5.1)** ajustando o engine; specifics documentados na subida.

| Serviço | Status | Engine (tenant DB) | Branch | Dir MCP | Notas |
|---|---|---|---|---|---|
| platform-dataforall-frontend | ✅ | — (SPA) | (product-dataforall) | — | borda do Tunnel |
| platform-api-gateway | ✅ | — (lê ADMIN) | develop | gateway_mcp | resolve tenant por Host |
| platform-mcp | ✅ | — (lê ADMIN) | develop | app (é o front-door) | 113 tools agregadas |
| platform-auth | ✅ | mysql | release/1.4.0 | mcp | assina JWT; JWKS |
| platform-admin | ✅ | mysql | develop | Dockerfile.admin-mcp (derivado) | IAM/usuários |
| platform-governance | ✅ | mysql | develop | mcp | ENV_PROFILE=hml; gov-mcp build defeito |
| platform-notification | ✅ | mysql | develop | mcp | Kafka OFF; notif-mcp agregação pendente |
| platform-cdc | ⬜ img✅ | mysql | develop | cdc_mcp | |
| platform-connectors | ✅ | mysql | develop | Dockerfile.mcp (raiz), 28000 | Fernet + OAUTH/WEBHOOK/FILE_PROXY secrets; MCP 235 tools |
| platform-analytics | ✅ | mysql | develop | Dockerfile.mcp (raiz), 7100 | BI; NOTIFICATION_INTERNAL_TOKEN+TRUSTED_PROXIES; MCP 117 tools |
| platform-communication | ⬜ img✅ | mysql | develop | mcp | |
| platform-ml | ⬜ img✗ | mysql | develop | mcp | build falhou |
| platform-monitor | ⬜ img✗ | mysql | develop | mcp | build falhou |
| platform-datalake | ⬜ img✗ | mysql | develop | mcp | build falhou |
| platform-docextract | ⬜ img✗ | mysql | develop | mcp | build falhou |
| platform-flow | ⬜ img✗ | mysql | develop | — | build falhou |
| platform-dai | ⬜ | mysql | fix/ci-oasdiff-baseline | mcp | branch de fix |
| platform-iceberg | ⬜ | mysql | develop | — | |
| platform-pipeline | ⬜ | mysql | develop | mcp | |
| platform-db-vector | ⬜ | mysql | develop | — | dívida: migrar p/ postgres+pgvector |
| platform-agents-factory | ⬜ | mysql | develop | mcp | |
| platform-security | ⬜ | mysql | (repo não clonado local) | ? | |
| platform-crm-agent | ⬜ | mysql | (não clonado) | ? | |
| platform-crm | ⬜ | postgres | (não clonado) | ? | |
| platform-marketing | ⬜ | postgres | (não clonado) | ? | |
| platform-marketing-agent | ⬜ | postgres | (não clonado) | ? | |
| platform-finance | ⬜ | postgres | (não clonado) | ? | |
| platform-finance-agent | ⬜ | postgres | (não clonado) | ? | |
| platform-sales | ⬜ | postgres | (não clonado) | ? | |
| platform-scheduler | ⬜ | postgres | (não clonado) | ? | |

> Para engine **postgres**: `DB_ENGINE=postgresql`, `DB_HOST=tenant-postgres`, `DB_PORT=5432`,
> `DB_USER=platform`, `DB_PASSWORD=••••` (=`POSTGRES_PASSWORD`).

### 5.1 Comuns a (quase) todos os serviços de app
| Variável | Valor | Notas |
|---|---|---|
| `APP_ENV` | `hml` | |
| `RUNTIME_ENV` | `local` | evita exigências cloud (Redis SSL/sentinel, Sentry, Kafka TLS, MFA) |
| `ENVIRONMENT` | `staging` | derivado de APP_ENV |
| `ENV_PROFILE` | `local-hml` | **exceção: governance usa `hml`** (`=APP_ENV`) |
| `NETWORK_TOPOLOGY` | `docker` | |
| `TZ` | `UTC` | |
| `DOCS_ENABLED` | `false` | |
| `UVICORN_WORKERS` | `1` | (platform-mcp: `GATEWAY_WORKERS=1`) |
| `ADMIN_DB_HOST` | `admin-mysql` | |
| `ADMIN_DB_PORT` | `3306` | |
| `ADMIN_DB_NAME` | `ADMIN_DATAFORALL` | |
| `ADMIN_DB_USER` | `root` | |
| `ADMIN_DB_PASSWORD` | `••••` | = `MYSQL_ROOT_PASSWORD` |
| `ADMIN_DB_SSLMODE` | `disable` | |
| `DB_ENGINE` | `mysql` | (postgres onde aplicável) |
| `DB_HOST` | `tenant-mysql` | |
| `DB_PORT` | `3306` | |
| `DB_NAME` | `dataforall` | = tenant_id |
| `DB_USER` | `root` | |
| `DB_PASSWORD` | `••••` | = `MYSQL_ROOT_PASSWORD` |
| `DB_SSLMODE` | `disable` | |
| `JWT_ALGORITHM` | `RS256` | |
| `JWT_ISSUER` | `platform-auth` | |
| `JWT_AUDIENCE` | `platform-services` | (auth assina com esse aud) |
| `JWT_JWKS_URL` | `http://platform-auth:8000/internal/.well-known/jwks.json` | |
| `INTERNAL_API_TOKEN` | `••••` | do `.env` |
| `OTEL_TRACES_ENABLED` | `true` | |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://otel-collector:4318` | |
| `CORS_ALLOWED_ORIGINS` | `["https://app.dataforall.tech"]` | |

### platform-api-gateway (#2) — específicos
`REDIS_URL=redis://:••••@redis:6379/0`, `REDIS_SSL=false`, `HEALTH_MONITORING_TOKEN=••••`,
`TRUSTED_PROXIES=["127.0.0.1/32","10.0.0.0/8","172.16.0.0/12"]`, `URL_AUTH=http://platform-auth:8000/internal`,
`URL_ADMIN=http://platform-admin:8000/api/v1`, `URL_IAM=http://platform-admin:8000/api/v1/iam`.
Porta publicada: `0.0.0.0:9999:8000` (frontend chega via host.docker.internal). Health: `:9090/health`.

### platform-auth (#3) — específicos
`RATE_LIMIT_STORAGE_URI=redis://:••••@redis:6379/0`, `JWT_PRIVATE_KEY_PATH=/run/secrets/jwt_key.pem`
(monta `secrets/jwt-auth.pem`), `URL_ADMIN`/`URL_IAM=http://platform-admin:8000/api/v1` (S2S DIRETO),
`VAULT_ADDR=http://vault:8200`, `VAULT_AUTH_METHOD=token`, `VAULT_TOKEN=••••`. Health: `:9090/health/ready`.

### platform-admin (#5) — específicos
`JWT_KEY_ID=platform-auth-1`, `JWT_PRIVATE_KEY_PATH=/run/secrets/jwt_key.pem` (MESMA chave do auth),
`JWT_SECRET_KEY=••••`, `CREDENTIAL_ENCRYPTION_KEY=••••`, `URL_AUTH=http://platform-auth:8000/api/v1/auth`,
`URL_IAM=http://platform-admin:8000/api/v1`. Health: `:9090/health/ready`. MCP: `ADMIN_MCP_ADMIN_URL`,
`ADMIN_MCP_INTERNAL_API_TOKEN=••••`, `ADMIN_MCP_MCP_PORT=7100`.

### platform-governance (#4) — específicos
`ENV_PROFILE=hml` (difere!), `JWT_SECRET_KEY=••••`, `CREDENTIAL_ENCRYPTION_KEY=••••`,
`MCP_SERVICE_TOKEN=••••` (=INTERNAL_API_TOKEN), `HEALTH_PORT=9090`. MCP: `MCP_GOVERNANCE_SERVICE_BASE_URL`,
`MCP_GOVERNANCE_SERVICE_TOKEN=••••`, `MCP_PORT=7103`.

### platform-mcp (gateway MCP central) — específicos
`ENVIRONMENT=staging`, `GATEWAY_WORKERS=1`, `GATEWAY_AUDIENCE=mcp:gateway`,
`URL_ADMIN_TWIN_JWKS=http://platform-admin:8000/api/v1/twin/jwks.json`,
`ADMIN_EXCHANGE_URL=http://platform-admin:8000/api/v1/twin/exchange`,
`GATEWAY_INTERNAL_TOKEN=••••` (=INTERNAL_API_TOKEN), `EXCHANGE_CACHE_TTL_SECONDS=45` (<60),
`REVOCATION_ENABLED=true`, `REGISTRY_SOURCE=db`, `REDIS_URL=redis://:••••@redis:6379/0`,
`NAMESPACE_URL_OVERRIDES={"admin":...,"auth":...,"governance":...,"api-gateway":...}`. Porta `127.0.0.1:8090:8000`.

### platform-notification — específicos
`JWT_EXPECTED_ISSUER=platform-auth`, `JWT_EXPECTED_AUDIENCE=platform-services`, `JWT_SECRET_KEY=••••`,
`CREDENTIAL_ENCRYPTION_KEY=••••`, `RATE_LIMIT_STORAGE_URI=redis://:••••@redis:6379/0`,
`KAFKA_ENABLED=false`, `KAFKA_CONSUMER_ENABLED=false`. Health: `:8000/api/health/ready`.
MCP: `NOTIFICATION_MCP_NOTIFICATION_URL`, `NOTIFICATION_MCP_INTERNAL_API_TOKEN=••••`,
`NOTIFICATION_MCP_DEFAULT_TENANT_ID=dataforall`, `NOTIFICATION_MCP_MCP_PORT=7100`.

### platform-connectors — específicos
`ENV_PROFILE=hml` (=APP_ENV), `HEALTH_PORT=9090` (health em `:9090/health/live`),
`JWT_SECRET_KEY=••••`, `CREDENTIAL_ENCRYPTION_KEY=••••` (Fernet, **obrigatória**),
`OAUTH_STATE_SECRET=••••`, `WEBHOOK_SECRET=••••`, `FILE_PROXY_SECRET=••••` (**os 3 obrigatórios fora de dev**),
`SERVICE_TENANT_ID=dataforall`, `URL_AUTH=http://platform-auth:8000/internal`,
`URL_IAM=http://platform-admin:8000/api/v1/iam`, `URL_GOVERNANCE=http://platform-governance:8000`,
`RATE_LIMIT_STORAGE_URI=redis://:••••@redis:6379/0`, `KAFKA_ENABLED=false`.
MCP (porta 28000, 235 tools): `CONNECTORS_MCP_CONNECTORS_URL=http://platform-connectors:8000`,
`CONNECTORS_MCP_INTERNAL_API_TOKEN=••••`, `CONNECTORS_MCP_DEFAULT_TENANT_ID=dataforall`,
`CONNECTORS_MCP_REQUEST_TIMEOUT=600`, `CONNECTORS_MCP_AUTH_URL=http://platform-auth:8000/internal`.

### platform-analytics — específicos
`ENV_PROFILE=hml` (=APP_ENV), `HEALTH_PORT=9090` (health `:9090/health/live`), `METRICS_ENABLED=true`,
`JWT_SECRET_KEY=••••`, `CREDENTIAL_ENCRYPTION_KEY=••••`, `INTERNAL_API_TOKEN=••••`,
`NOTIFICATION_INTERNAL_TOKEN=••••` (**obrigatório**), `TRUSTED_PROXIES=[...]` (**obrigatório, não-vazio**),
`RATE_LIMIT_STORAGE_URI=redis://:••••@redis:6379/0`, `KAFKA_ENABLED=false` (default é true! forçado OFF),
`URL_GOVERNANCE=http://platform-governance:8000`, `URL_IAM=http://platform-admin:8000/api/v1/iam`,
`NOTIFICATION_SERVICE_URL=http://platform-notification:8000`.
MCP (porta 7100, 117 tools): `ANALYTICS_MCP_ANALYTICS_URL=http://platform-analytics:8000`,
`ANALYTICS_MCP_INTERNAL_API_TOKEN=••••`, `ANALYTICS_MCP_DEFAULT_TENANT_ID=dataforall`, `ANALYTICS_MCP_TWIN_ENFORCE=false`.

---

## 6. Infra containers (`deploy/docker-compose.infra.yml`)

Referenciam do `.env`: `MYSQL_ROOT_PASSWORD`, `POSTGRES_PASSWORD`, `REDIS_PASSWORD`,
`VAULT_ROOT_TOKEN` (→ `VAULT_DEV_ROOT_TOKEN_ID`), `GRAFANA_ADMIN_PASSWORD`. Portas em `127.0.0.1`
(hardening): admin-mysql 53306, tenant-mysql 3306, tenant-postgres 5432, redis 6379, vault 8200.

> **Manutenção:** ao setar uma variável nova em qualquer serviço, adicione-a aqui (mascarando
> se for segredo). Relaciona-se a [bring-up-errors-and-fixes.md](bring-up-errors-and-fixes.md) e
> [bring-up-from-scratch.md](bring-up-from-scratch.md).
