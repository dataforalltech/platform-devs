# Inventário de variáveis de ambiente — ambiente enxuto

> Todas as variáveis configuradas para subir o ambiente enxuto, por escopo.
> **Senhas/tokens estão mascarados** (`••••`); a coluna "Origem" diz de onde vem o valor real.
> Valores concretos vivem no `.env` on-box (chmod 600), no SSM (SecureString) ou no
> ambiente Windows local — **nunca** no git.

Legenda de origem: **on-box** = gerado na EC2 no bring-up (`.env`); **SSM** = AWS SSM
Parameter Store (cifrado KMS); **local** = ambiente Windows do operador; **fixo** = valor
não-secreto definido no compose/terraform.

> **Estado (2026-07-06):** 13 APIs + 9 MCP no ar (inclui o **lakehouse iceberg**: MinIO+Polaris+Trino, SQL validado);
> front-door agregando **705 tools / 21 serviços**; login e2e 200.
> Roster completo (subidos + pendentes) na §5.0. Guia operacional: [bring-up-from-scratch.md](bring-up-from-scratch.md).

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
| `JWT_SECRET_KEY` | `••••` (hex 40) | on-box | quase todos (auth/admin/governance/notification/connectors/analytics/communication/ml/monitor/agents-factory) |
| `CREDENTIAL_ENCRYPTION_KEY` | `••••` (Fernet 44) | on-box | quase todos (admin/governance/notification/connectors/analytics/communication/ml/monitor/agents-factory — `FERNET_KEY` no agents-factory) |
| `OAUTH_STATE_SECRET` | `••••` (hex 32) | on-box | connectors (assina state OAuth) |
| `WEBHOOK_SECRET` | `••••` (hex 32) | on-box | connectors (assina tokens de webhook PIX/PSP) |
| `FILE_PROXY_SECRET` | `••••` (hex 32) | on-box | connectors (assina URLs do file proxy) |
| `ICEBERG_MINIO_USER` / `ICEBERG_MINIO_PASSWORD` | `••••` | on-box | MinIO root + s3 keys do Trino/Polaris (iceberg) |
| `ICEBERG_POLARIS_SECRET` | `••••` (32) | on-box | Polaris bootstrap root + OAuth (API/Trino/hml-init) |
| `ICEBERG_API_TOKEN` | `••••` (hex 24) | on-box | iceberg API (auth estática) + token interno do MCP |
| `ICEBERG_MCP_SERVICE_TOKEN` / `ICEBERG_SECRET_KEY` | `••••` | on-box | iceberg MCP (HMAC, adiado) / Fernet do registry |

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
| platform-cdc | ✅ | mysql | develop | mcp/Dockerfile (raiz), 28000 | ENV_PROFILE=local-hml; Kafka/coord OFF; MCP 9 tools |
| platform-connectors | ✅ | mysql | develop | Dockerfile.mcp (raiz), 28000 | Fernet + OAUTH/WEBHOOK/FILE_PROXY secrets; MCP 235 tools |
| platform-analytics | ✅ | mysql | develop | Dockerfile.mcp (raiz), 7100 | BI; NOTIFICATION_INTERNAL_TOKEN+TRUSTED_PROXIES; MCP 117 tools |
| platform-communication | ✅ | mysql | develop | mcp/Dockerfile (própria img — K5 resolvido) | ENV_PROFILE=local-hml; CMD override (K6); MCP 65 tools |
| platform-ml | ✅ | mysql | develop | mcp/Dockerfile (7104) | **PULL** (img enxuta CPU-only); ENV_PROFILE=hml; alembic-inject (L3); MySQL-patch (L4); notif OFF (L2); MCP 71 tools |
| platform-monitor | ✅ | mysql | develop | mcp/Dockerfile (28000, ctx=mcp/ — J6) | health `:9090`; **NÃO** usa ENV_PROFILE; migrations SQL (`apply_mysql_migrations.sh`, tabelas `mon_`); MCP 23 tools |
| platform-agents-factory | ✅ | mysql | develop | Dockerfile.mcp (7130) | build; ENV_PROFILE=local-hml; LLM keys lazy; MCP 10 tools |
| platform-datalake | ⬜ img✗ | mysql | develop | mcp | build falhou (git+ssh — tarefa de repo) |
| platform-docextract | ⬜ img✗ | mysql | develop | mcp | build falhou (sem git no Dockerfile — tarefa de repo) |
| platform-flow | ⬜ img✗ | mysql | develop | — | build falhou (git+ssh — tarefa de repo) |
| platform-dai | ⬜ | mysql | fix/ci-oasdiff-baseline | mcp | branch de fix |
| platform-iceberg | ✅ (lakehouse) | — (JsonStore) | develop | local (não em develop) | **stack: MinIO+Polaris+Trino** (rede `iceberg-net`); API auth por `API_TOKEN`; SQL validado; MCP adiado (M4) |
| platform-pipeline | ⬜ | mysql | develop | mcp | |
| platform-db-vector | ⬜ | mysql | develop | — | dívida: migrar p/ postgres+pgvector |
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

### platform-communication — específicos
`ENV_PROFILE=local-hml`, `JWT_SECRET_KEY=••••`, `CREDENTIAL_ENCRYPTION_KEY=••••`,
`INTERNAL_API_TOKEN=••••`, `NOTIFICATION_INTERNAL_TOKEN=••••`, `RATE_LIMIT_STORAGE_URI=redis://:••••@redis:6379/0`,
`KAFKA_ENABLED=false`, `HEALTHCHECK_TENANT_ID=dataforall`. **CMD override** (`--limit-max-requests`, o
bakado usa `--max-requests` inválido — K6). Health `:8000/api/health/live`.
**MCP — ÚNICO caso sem imagem própria:** desenhado p/ rodar da MESMA imagem da API via `MCP_HTTP_MODE=1`
+ `MCP_HTTP_PORT` + `python -m src.server.mcp_server` (prefixo `MCP_REPO_*`). Hoje PENDENTE (K5: o `mcp/`
não está na imagem da API e o repo não tem Dockerfile de MCP).

### platform-cdc — específicos
`ENV_PROFILE=local-hml` (**{runtime}-{app}**, como o core — difere de governance/connectors/analytics),
health `:8000/api/health/ready`, `INTERNAL_API_TOKEN=••••`, `URL_AUTH=http://platform-auth:8000/internal`,
`CONNECTORS_SERVICE_URL=http://platform-connectors:8000`, `RATE_LIMIT_STORAGE_URI=redis://:••••@redis:6379/0`.
CDC standalone (sem streaming ativo): `KAFKA_ENABLED=false`, `KAFKA_CONSUMER_ENABLED=false`,
`CDC_COORDINATOR_ENABLED=false` (senão exige `TENANT_ID`), `CDC_WORKER_STANDALONE=true`, `MONITOR_EVENTS_ENABLED=false`.
MCP (porta 28000, 9 tools, `/mcp/tools/list`): `MCP_HTTP_PORT=28000`, `CDC_INTERNAL_URL=http://platform-cdc:8000/api/v1`,
`CDC_INTERNAL_TOKEN=••••`, `CDC_MCP_TWIN_ENFORCE=false` (senão exige twin JWKS no boot).

### platform-ml — específicos (imagem ENXUTA via PULL, não build)
`ENV_PROFILE=hml` (**=APP_ENV**, difere do core), `JWT_SECRET_KEY=••••`, `CREDENTIAL_ENCRYPTION_KEY=••••`,
`INTERNAL_API_TOKEN=••••`. ML CPU-only: `ML_METADATA_BACKEND=db`, `MODEL_REGISTRY_BACKEND=db`,
`MODEL_REGISTRY_PATH=/data/platform-ml/model-registry` (volume `ml-model-registry`), `ML_USE_GPU=false`,
`ML_WHISPER_DEVICE=cpu`, `ONNX_RUNTIME_ENABLED=false`. `URL_GOVERNANCE=http://platform-governance:8000`.
`RATE_LIMIT_STORAGE_URI`/`REDIS_URL=redis://:••••@redis:6379/0`, `KAFKA_ENABLED=false`. Health `:8000/api/health/live`.
**`NOTIFICATION_SERVICE_URL=""`** (vazio de propósito — cliente de notificação com contrato defasado derruba o boot; L2).
**Init-container** `platform-ml-init` faz `chown 1000` no volume (L1). **Bind-mount** `alembic-inject/` → `/app/alembic*`
(imagem enxuta não traz alembic; L3). Provisionar tabelas: `docker exec platform-ml python /app/scripts/bootstrap_tenants.py`
(42 tabelas `ml_*`). MCP (porta 7104, 71 tools, `/mcp/tools/list`+`/mcp/tools/call`, `/v1/health`):
`MCP_ML_HTTP=1`, `MCP_PORT=7104`, `MCP_ML_SERVICE_BASE_URL=http://platform-ml:8000`,
`ML_MCP_SERVICE_TOKEN=••••`, `ML_MCP_TWIN_ENFORCE=0`.

### platform-agents-factory — específicos
`ENV_PROFILE=local-hml` (**{runtime}-{app}**), `JWT_SECRET_KEY=••••` (obrigatório explícito), `JWT_ACCESS_TOKEN_EXPIRE_MINUTES=240`,
`CREDENTIAL_ENCRYPTION_KEY=••••`, `FERNET_KEY=••••` (=CREDENTIAL_ENCRYPTION_KEY), `INTERNAL_API_TOKEN=••••`,
`AGENTS_RUNTIME=lib`, `LAB_MODE=false`, `AUTH_DEV_BYPASS=false`, `URL_AUTH=http://platform-auth:8000/internal`,
`URL_IAM=http://platform-admin:8000/api/v1/iam`, `RATE_LIMIT_STORAGE_URI`/`REDIS_URL=redis://:••••@redis:6379/0`,
`KAFKA_ENABLED=false`. **LLM keys (OpenAI/Anthropic) são LAZY** (resolvidas do DB por tenant — não precisam no boot).
Migrations rodam no boot (non-fatal, `alembic_version_agents_factory`, revisões 0001–0005). Health `:8000/api/health/live`.
MCP (porta 7130, 10 tools, `Dockerfile.mcp`): `AGENTS_FACTORY_MCP_FACTORY_URL=http://platform-agents-factory:8000`,
`AGENTS_FACTORY_MCP_INTERNAL_API_TOKEN=••••`, `AGENTS_FACTORY_MCP_DEFAULT_TENANT_ID=dataforall`,
`AGENTS_FACTORY_MCP_MCP_PORT=7130`, `JWT_SECRET_KEY=••••`, `JWT_ALGORITHM=RS256`,
`AGENTS_FACTORY_MCP_JWT_ISSUER=platform-auth`, `AGENTS_FACTORY_MCP_JWT_AUDIENCE=platform-services`.

### platform-monitor — específicos
**NÃO usa `ENV_PROFILE`** (o repo não valida esse campo). Health server em **porta separada 9090** (`/health/ready`) —
`HEALTH_PORT=9090`, `APP_HOST=0.0.0.0`, `APP_PORT=8000`, `UVICORN_WORKERS=1`. `LOG_LEVEL=INFO` (DEBUG proibido),
**`MONITOR_ALLOW_PRIVATE_URLS=false`** (SSRF-01, obrigatório), `SCHEDULER_ENABLED=true`, `JWT_ALGORITHM=RS256` (AUTH-15),
`JWT_SECRET_KEY=••••`, `CREDENTIAL_ENCRYPTION_KEY=••••`, `INTERNAL_API_TOKEN=••••`,
`NOTIFICATION_SERVICE_URL=http://platform-notification:8000`, `NOTIFICATION_INTERNAL_TOKEN=••••`,
`RATE_LIMIT_STORAGE_URI`/`REDIS_URL=redis://:••••@redis:6379/0`, `KAFKA_ENABLED=false`, `KAFKA_CONSUMER_ENABLED=false`.
Migrations são **SQL puro** (não alembic): `docker exec platform-monitor bash ./scripts/apply_mysql_migrations.sh` (tabelas `mon_`, 10).
MCP (porta 28000, 23 tools, `mcp/Dockerfile` **ctx=`mcp/`** — J6): `MONITOR_MCP_SERVICE_BASE_URL=http://platform-monitor:8000`,
`MONITOR_MCP_HEALTH_BASE_URL=http://platform-monitor:9090`, `MONITOR_MCP_TWIN_ENFORCE=false`, e **`ADMIN_DB_*`**
(o MCP resolve `X-Internal-Token` por-tenant do `ADMIN_DATAFORALL.PLATFORMS`).

### platform-iceberg — LAKEHOUSE (MinIO + Polaris + Trino) — ver runbook M
**Não segue o padrão comum** — é um control-plane num data-stack próprio (rede `iceberg-net`; API+MCP também no `platform-local`).
`ENVIRONMENT=homologacao` (relaxa validações de prod/staging), **auth por `API_TOKEN` estático** (não JWT/JWKS), registry **JsonStore**
(volume, sem DATABASE_URL). API (porta 8018, health `:8018/api/health/live`): `API_TOKEN=••••` (=`ICEBERG_API_TOKEN`),
`SECRET_KEY=••••` (Fernet), `TRINO_HOST=trino`/`TRINO_PORT=8080`/`TRINO_HTTP_SCHEME=http`, `POLARIS_BASE_URL=http://polaris:8181`,
`POLARIS_HEALTH_URL=http://polaris:8182/q/health/live`, `POLARIS_CLIENT_ID=root`, `POLARIS_CLIENT_SECRET=••••`, `POLARIS_OAUTH_SCOPE=PRINCIPAL_ROLE:ALL`.
Data-stack: **minio** (`RELEASE.2024-10-02`, `MINIO_ROOT_USER/PASSWORD=••••`, bucket `warehouse`); **polaris** (`apache/polaris:1.4.0`,
`POLARIS_PERSISTENCE_TYPE=in-memory` — M1, `POLARIS_BOOTSTRAP_CREDENTIALS=POLARIS,root,••••`, `AWS_*`/`QUARKUS_S3_*`→minio); **trino**
(`trinodb/trino:465` — M2, `mem_limit 3g` + jvm.config `-Xmx2G` — M3, catalog `tenant_lab_s3` OAUTH2 scope `PRINCIPAL_ROLE:ALL`,
s3/oauth creds via `${ENV:...}` = `S3_ACCESS_KEY`/`S3_SECRET_KEY`/`POLARIS_CLIENT_SECRET`). **hml-init** cria o catalog+schema+seed (idempotente).
**MCP adiado** (M4). Segredos: `ICEBERG_*` no `.env`.

---

## 6. Infra containers (`deploy/docker-compose.infra.yml`)

Referenciam do `.env`: `MYSQL_ROOT_PASSWORD`, `POSTGRES_PASSWORD`, `REDIS_PASSWORD`,
`VAULT_ROOT_TOKEN` (→ `VAULT_DEV_ROOT_TOKEN_ID`), `GRAFANA_ADMIN_PASSWORD`. Portas em `127.0.0.1`
(hardening): admin-mysql 53306, tenant-mysql 3306, tenant-postgres 5432, redis 6379, vault 8200.

> **Manutenção:** ao setar uma variável nova em qualquer serviço, adicione-a aqui (mascarando
> se for segredo). Relaciona-se a [bring-up-errors-and-fixes.md](bring-up-errors-and-fixes.md) e
> [bring-up-from-scratch.md](bring-up-from-scratch.md).
