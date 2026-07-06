# Bring-up do ambiente enxuto — Erros, causas e correções

> **Objetivo:** registrar **todos** os erros encontrados ao subir o ambiente enxuto
> (1 EC2 + Cloudflare Tunnel, `us-east-1`) pela primeira vez, com **evidência**,
> **causa-raiz** e **correção**, para que a VM suba **limpa** nas próximas vezes.
>
> Coluna **Status**: `✅ bakado` = correção já está no script/compose versionado;
> `⚙️ seed` = precisa estar no seed/bootstrap (ver ação); `📌 gotcha` = comportamento
> esperado, não é bug; `⏳ pendente` = ainda sem correção definitiva.
>
> Ambiente de referência: EC2 `t3.xlarge` Ubuntu 22.04, Docker 29 + Compose v5,
> projeto compose `dataforall-infra`, rede externa `platform-local`, Docker
> `data-root=/data/docker` (EBS 100G). Conta AWS `011756140303`, região `us-east-1`.

---

## A. Terraform / Infra AWS

### A1. Cloudflare Tunnel — Authentication error (10000)
- **Evidência:** `Error: Authentication error (10000)` ao criar `cloudflare_zero_trust_tunnel_cloudflared` no `terraform apply`.
- **Causa:** o token da Cloudflare não tinha permissão de **Account → Cloudflare Tunnel → Edit**.
- **Correção:** usar o token **`platform-infra-dev`** (tem *Cloudflare Tunnel Read/Write*). Ler via `CLOUDFLARE_API_TOKEN`. **Status:** ✅ (token correto em uso).

### A2. Security Group / DLM — descrição não-ASCII rejeitada
- **Evidência:** `InvalidParameterValue` no `aws_security_group`/`aws_dlm_lifecycle_policy` com descrição contendo `—` (em-dash) e `único`.
- **Causa:** AWS aceita apenas ASCII em `description` de SG e DLM.
- **Correção:** descrições em ASCII puro (`"Host unico - sem ingress..."`). **Status:** ✅ bakado (`terraform-lean/main.tf`, `compute.tf`).

### A3. Cloudflare — registro apex já existe
- **Evidência:** `Error: expected DNS record to not already be present but already exists` em `cloudflare_record.apex`.
- **Causa:** a raiz `dataforall.tech` já tinha um registro na zona; e a raiz **não é tenant** (tenants são subdomínios cobertos pelo wildcard).
- **Correção:** remover `cloudflare_record.apex` do Terraform (não gerenciar a raiz). **Status:** ✅ bakado (`tunnel.tf`).

### A4. S3 — nome de bucket global travado após destroy (~1h)
- **Evidência:** `aws_s3_bucket.backups` ficou `Still creating...` por `59m41s` ao recriar logo após um `destroy`.
- **Causa:** nome de bucket S3 é **global**; a AWS segura a reutilização por um tempo após a exclusão.
- **Correção:** não recriar o mesmo nome imediatamente após destroy (esperar), ou usar sufixo novo. **Status:** 📌 gotcha (comportamento AWS).

---

## B. EC2 / Docker / Infra compose

### B1. AWS CLI no Windows — `charmap codec can't encode`
- **Evidência:** `aws: [ERROR]: 'charmap' codec can't encode characters in position ...` ao ler output com não-ASCII (Git Bash/Windows).
- **Causa:** encoding padrão do Python no Windows não é UTF-8.
- **Correção:** `export PYTHONIOENCODING=utf-8 PYTHONUTF8=1` antes dos comandos `aws`. **Status:** 📌 gotcha (ambiente local).

### B2. Env vars de escopo User do Windows não chegam ao shell
- **Evidência:** `CLOUDFLARE_API_TOKEN` vazio no shell mesmo definido no Windows.
- **Causa:** vars User definidas após o processo iniciar não são herdadas.
- **Correção:** ler via `powershell [Environment]::GetEnvironmentVariable('NOME','User')`. **Status:** 📌 gotcha.

### B3. Git Bash — path mangling em nomes de parâmetro SSM
- **Evidência:** `ValidationException ... Parameter name must be a fully qualified name` ao usar `/dataforall-hml/...`.
- **Causa:** MSYS (Git Bash) converte `/foo/bar` em caminho Windows.
- **Correção:** `export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*'`. **Status:** 📌 gotcha (só no Windows; na EC2 Linux não ocorre).

### B4. `s3 sync` — AccessDenied em `kms:Decrypt`
- **Evidência:** `AccessDenied ... not authorized to perform: kms:Decrypt on resource: arn:aws:kms:...` ao sincronizar `deploy/` do S3 na EC2.
- **Causa:** o bucket é cifrado com KMS e o instance profile **não** tinha `kms:Decrypt`.
- **Correção:** adicionar `kms:Decrypt/Encrypt/GenerateDataKey/DescribeKey` no `aws_iam_role_policy.host`. **Status:** ✅ bakado (`terraform-lean/main.tf`, stmt `KmsForBackupsBucket`).

### B5. Docker — rede externa `platform-local` não encontrada
- **Evidência:** `network platform-local declared as external, but could not be found`.
- **Causa:** o compose declara a rede como `external: true`; ela precisa existir antes.
- **Correção:** `docker network create platform-local`. **Status:** ✅ bakado (`terraform-lean/scripts/bringup-infra.sh`).

### B6. Docker — volumes no disco root (40G) em vez do /data (100G)
- **Evidência:** volumes em `/var/lib/docker` (root de 40G); risco de encher o disco.
- **Causa:** `data-root` padrão do Docker.
- **Correção:** `/etc/docker/daemon.json` com `"data-root": "/data/docker"` + `systemctl restart docker`. **Status:** ✅ bakado (`bringup-infra.sh`).

### B7. MySQL 8.4 — `unknown variable 'default-authentication-plugin'`
- **Evidência:** `[ERROR] [MY-000067] unknown variable 'default-authentication-plugin=caching_sha2_password'` → container em restart-loop.
- **Causa:** o flag `--default-authentication-plugin` foi **removido no MySQL 8.4**.
- **Correção:** trocar por `--authentication-policy=caching_sha2_password`. **Status:** ✅ bakado (`deploy/docker-compose.infra.yml`).

### B8. MySQL — datadir meio-inicializado após o crash do B7
- **Evidência:** `The privilege system failed to initialize correctly` / `Table 'mysql.component' doesn't exist`.
- **Causa:** o crash do flag abortou o init do datadir, deixando-o corrompido; restart reaproveita o volume corrompido.
- **Correção:** remover os volumes e recriar: `docker compose rm -sf admin-mysql tenant-mysql && docker volume rm dataforall-infra_admin-mysql-data dataforall-infra_tenant-mysql-data && up -d`. **Status:** ✅ prevenido (B7 corrigido → não recorre em VM limpa). Nome real do volume = `dataforall-infra_<svc>-data`.

---

## C. Segredos / `.env`

### C1. `.env` apagado pelo `aws s3 sync --delete`
- **Evidência:** após um bring-up, `.env` só tinha 2 chaves; DBs seguiam de pé mas `grep MYSQL_ROOT_PASSWORD .env` retornava vazio.
- **Causa:** `aws s3 sync s3://.../deploy /opt/dataforall/deploy --delete` **apaga** arquivos locais ausentes no S3 — e o `.env` (senhas geradas on-box) nunca vai pro S3.
- **Correção:** **sempre** usar `--exclude ".env"` (e `--exclude "secrets/*"`) nos syncs. **Status:** ✅ bakado (`bringup-infra.sh`, `deploy/frontend/bringup.sh`, `deploy/services/*/bringup.sh`).
- **Recuperação (se acontecer):** os segredos são recuperáveis dos containers em execução:
  `docker exec dataforall-admin-mysql printenv MYSQL_ROOT_PASSWORD` (idem `POSTGRES_PASSWORD`, `VAULT_DEV_ROOT_TOKEN_ID`, `GF_SECURITY_ADMIN_PASSWORD`); Redis: `docker inspect dataforall-redis` → arg após `--requirepass`.

### C2. `set -e` + `[ -z x ] && cmd` aborta o script
- **Evidência:** script SSM falhava (exit 1) sem output após a 1ª atribuição.
- **Causa:** com `set -e`, `[ -z "$X" ] && Y` retorna exit 1 quando o teste é falso → aborta.
- **Correção:** usar `if [ -z "$X" ]; then Y; fi`. **Status:** ✅ bakado (scripts revisados).

### C3. SSM `PutParameter` — AccessDenied na EC2
- **Evidência:** a chave RSA gerada on-box não persistiu no SSM (`describe-parameters` vazio); `put-parameter` falhou silencioso (`>/dev/null`).
- **Causa:** o instance profile tem `ssm:GetParameter*` em `/dataforall-hml/*`, mas **não** `ssm:PutParameter`.
- **Correção:** para segredos gerados na EC2, persistir no **S3** (a EC2 tem `s3:PutObject`), ex.: `s3://<bucket>/secrets/`. (Alternativa: conceder `ssm:PutParameter` ao role.) **Status:** ✅ bakado (chave do auth vai pra `s3://.../secrets/platform-auth-jwt.pem`).

---

## D. Frontend (#1)

### D1. `/` retorna 403 para `curl`/`wget`
- **Evidência:** `curl https://app.dataforall.tech/` → `403 Forbidden`; logs mostram scanners também com 403.
- **Causa:** **anti-scraping gate** do nginx bloqueia User-Agents não-navegador (`curl|wget|python-requests|...` no `nginx.conf`).
- **Correção:** testar com UA de browser (`-A "Mozilla/5.0 ... Chrome/120"`); `/healthz` é isento. **Status:** 📌 gotcha (comportamento by design). Validado: com UA de browser → `200`.

---

## E. platform-api-gateway (#2)

### E1. `ValidationError: ENV_PROFILE inconsistente`
- **Evidência:** `ENV_PROFILE ('cloud-hml') is inconsistent with RUNTIME_ENV='local' and APP_ENV='hml'. Expected: 'local-hml'`.
- **Causa:** validador exige `ENV_PROFILE == {RUNTIME_ENV}-{APP_ENV}`.
- **Correção:** `ENV_PROFILE=local-hml` (com `RUNTIME_ENV=local` + `APP_ENV=hml`). **Status:** ✅ bakado (compose do gateway; **mesmo padrão vale para TODOS os serviços**).

### E2. Frontend não alcança o gateway em `127.0.0.1:9999`
- **Evidência:** `/api` no frontend dava erro de conexão; gateway publicado em `127.0.0.1:9999`.
- **Causa:** o container do frontend chega no gateway via `host.docker.internal:9999` (IP do host na bridge); um bind em **loopback** não é alcançável por containers.
- **Correção:** publicar o gateway em `0.0.0.0:9999` (`"9999:8000"`). SG fechado mantém inacessível de fora. **Status:** ✅ bakado (compose do gateway).

### E3. Healthcheck do gateway → 403
- **Evidência:** `GET /api/health/ready` no healthcheck → `403 Forbidden` (container marcado unhealthy).
- **Causa:** a porta 8000 passa pelo `DomainTenantMiddleware`, que exige Host de tenant conhecido; o probe usa `Host: localhost`.
- **Correção:** healthcheck no **health server interno** `:9090/health` (não passa pelo middleware). **Status:** ✅ bakado (compose do gateway).

### E4. `GATEWAY_MAPPING.internal_url` aponta para `localhost` → 502
- **Evidência:** `POST /api/v1/auth/login` → `502`; logs do gateway: rotas `http://localhost:5080`, etc.
- **Causa:** o bootstrap do gateway semeia `GATEWAY_MAPPING` com `http://localhost:<porta>` (assume host-networking), mas no compose os serviços são alcançáveis por **nome de container**.
- **Correção:** `UPDATE ADMIN_DATAFORALL.GATEWAY_MAPPING SET internal_url='http://<container>:8000' WHERE name_microservice='<svc>'` + `docker restart platform-api-gateway`. **Status:** ⚙️ seed — **precisa ser feito para cada serviço** ao subir (ver §G, ação recorrente).

---

## F. platform-auth (#3)

### F1. JWKS 503 — `RSA private key not configured`
- **Evidência:** `GET /internal/.well-known/jwks.json` → `503 {"message":"RSA private key not configured. Set JWT_PRIVATE_KEY_CONTENT or JWT_PRIVATE_KEY_PATH."}`.
- **Causa:** a integração Vault→config **não wireia** a chave neste build (o `vault_loader` existe, mas o JWKS lê `JWT_PRIVATE_KEY_CONTENT/PATH` do settings).
- **Correção:** fornecer a chave via **arquivo montado** + `JWT_PRIVATE_KEY_PATH=/run/secrets/jwt_key.pem` (fonte durável: `s3://.../secrets/platform-auth-jwt.pem`, também seedada no Vault `kv/dataforall/platform-auth/jwt_private_key`). **Status:** ✅ bakado (compose do auth). **Dívida D5:** migrar p/ Vault quando houver Vault de produção.

### F2. JWKS 500 — `PermissionError` na chave montada
- **Evidência:** `PermissionError: [Errno 13] Permission denied: '/run/secrets/jwt_key.pem'`.
- **Causa:** arquivo `chmod 600` dono root no host; o processo do auth roda como usuário **não-root** no container → não lê.
- **Correção:** `chmod 644` no arquivo da chave (host single-tenant, SG fechado, acesso só via SSM). **Status:** ⚙️ seed — o script do auth deve gravar a chave com `chmod 644`.

### F3. Health server `:9090` — `address already in use`
- **Evidência:** `[Errno 98] error while attempting to bind on address ('0.0.0.0', 9090): address already in use` repetido; "Child process died".
- **Causa:** `uvicorn --workers 2` faz cada worker tentar subir o health server na mesma porta.
- **Correção:** `UVICORN_WORKERS=1`. **Status:** ✅ bakado (compose do auth).

### F4. Tenant DB — `Access denied for user 'root' (using password: NO)`
- **Evidência:** `pymysql.err.OperationalError: (1045, "Access denied for user 'root'@'...' (using password: NO)")`.
- **Causa:** o auth resolve as credenciais do DB do tenant das colunas **`db_user`/`db_password` do `PLATFORMS`** (`db_password = platform.get("db_password") or ""`), e o seed inicial (schema do gateway) **não tinha** essas colunas → senha vazia.
- **Correção:** `ALTER TABLE ADMIN_DATAFORALL.PLATFORMS ADD COLUMN db_user VARCHAR(255) NULL, ADD COLUMN db_password VARCHAR(500) NULL;` + `UPDATE ... SET db_user='root', db_password='<MYSQL_ROOT_PASSWORD>' WHERE tenant_id='dataforall';`. **Status:** ⚙️ seed — **incluir db_user/db_password no seed do PLATFORMS** (§G).

### F5. Tenant DB — `Unknown database 'dataforall'`
- **Evidência:** `pymysql.err.OperationalError: (1049, "Unknown database 'dataforall'")`.
- **Causa:** o auth usa **1 database por tenant, nomeado pelo `tenant_id`** (`dataforall`), não `platform_auth`.
- **Correção:** `CREATE DATABASE IF NOT EXISTS dataforall CHARACTER SET utf8mb4;` no tenant-mysql. **Status:** ⚙️ seed — criar o DB do tenant no seed (§G).

### F6. Login 403 — `integration_error [403] POST /auth: UNKNOWN_DOMAIN`
- **Evidência:** `httpx: POST http://platform-api-gateway:8000/api/v1/admin/auth "HTTP/1.1 403 Forbidden"` → `Integration error [POST /auth]: [403] ... This domain is not associated with any tenant.`
- **Causa:** o auth chama **de volta o gateway** (padrão gateway-único) para falar com o `platform-admin`; essa chamada interna usa `Host: platform-api-gateway:8000`, que **não é domínio de tenant** → o `DomainTenantMiddleware` rejeita.
- **Correção:** **pendente** — duas frentes: (a) subir `platform-admin` (#5); (b) fazer o gateway **aceitar chamadas internas** (com `X-Internal-Token`+`X-Tenant-Id`) sem exigir resolução de domínio, OU o cliente interno enviar `Host`/`X-Forwarded-Host` = domínio do tenant. **Status:** ⏳ pendente (decisão do usuário: subir admin e integrar o trio).

---

## G. Ações de SEED recorrentes (para VM limpa)

Estas correções foram aplicadas ao vivo e **precisam entrar no bootstrap** para uma VM
subir limpa. Consolidar em um script de seed do admin DB executado após a infra:

1. **Schema `PLATFORMS` completo** (inclui `db_user`/`db_password` — usados pelo auth):
   ```sql
   CREATE DATABASE IF NOT EXISTS ADMIN_DATAFORALL CHARACTER SET utf8mb4;
   CREATE TABLE IF NOT EXISTS ADMIN_DATAFORALL.PLATFORMS ( ... , db_user VARCHAR(255) NULL, db_password VARCHAR(500) NULL, ... );
   INSERT ... PLATFORMS (..., domain, db_engine, db_host, db_port, db_user, db_password, ...)
     VALUES (..., 'app.dataforall.tech','mysql','tenant-mysql',3306,'root','<MYSQL_ROOT_PASSWORD>', ...);
   ```
2. **Database por tenant** (nomeado pelo `tenant_id`): `CREATE DATABASE IF NOT EXISTS dataforall;`
3. **`GATEWAY_MAPPING.internal_url`** para cada serviço → nome de container:
   `UPDATE GATEWAY_MAPPING SET internal_url='http://<svc>:8000' WHERE name_microservice='<svc>';`
   (executar ao subir cada serviço, seguido de `docker restart platform-api-gateway`).
4. **Chave RSA do auth** gravada com `chmod 644` em `/opt/dataforall/deploy/secrets/jwt-auth.pem`.

> **TODO:** consolidar 1–4 em `deploy/seed/seed-admin-db.sh` idempotente e chamá-lo
> no fluxo de bring-up, para eliminar os passos manuais.

---

## H. Ordem de bring-up limpo (resumo)

1. `terraform apply` (infra: EC2, tunnel, DNS, KMS, S3, IAM com kms:Decrypt + SSM read).
2. `bringup-infra.sh` (data-root /data, rede platform-local, `.env` on-box, `up -d` infra).
3. **seed-admin-db.sh** (ADMIN_DATAFORALL + PLATFORMS c/ db_user/db_password + DB por tenant). *(a consolidar)*
4. Frontend → Gateway → Auth → Governance → Admin → demais, cada um API + MCP, e a cada serviço: fixar `GATEWAY_MAPPING.internal_url`.
5. Integração final: chamadas internas via gateway (bypass de domínio), usuários seed, login e2e.
