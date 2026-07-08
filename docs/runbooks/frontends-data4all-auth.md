# Auth dos 4 frontends de produto (.com.br) — integração HML

**Data:** 2026-07-08. Complementa [frontends-data4all-bringup.md](frontends-data4all-bringup.md).

Descoberta ao subir os 4: **cada produto tem um modelo de login diferente** (endpoint + tabela + hashing). O onboarding só semeou `adm_users` (platform-auth), que serve apenas o sales. Integração de cada um abaixo.

## Mapa de auth

| Frontend | Domínio | Endpoint (front) | Backend / rota | Tabela · hashing | Como ficou |
|---|---|---|---|---|---|
| **sales** | sales.data4all.com.br | `/auth/login` | platform-auth (gateway `/auth`) | `adm_users` · bcrypt | ✅ já funcionava (seed `adm_users`) |
| **admin** | admin.data4all.com.br | `/customers/login` | platform-dataforall-admin `:25987` | `ADMIN_DATAFORALL.CUSTOMERS` · bcrypt | ✅ rota `/customers` no gateway + `seed-admin-customer.sh` |
| **customer-admin** | platform.d4all.com.br | `/auth/login` | **backend próprio** `dataforall-customer-admin:8000` | `accounts` (tenant DB) · **Argon2id** | ✅ **product-native** (nginx próprio do front) + migrations + `seed-customer-account.sh` |
| **partners** | partner.data4all.com.br | ~~`/public/partner-auth/login`~~ → `/auth/login` | platform-auth | `adm_users` · bcrypt | ✅ **unificado** (endpoint não existia no backend) + seed `adm_users` |

## Decisões / detalhes

- **admin (product-native, gateway):** o gateway roteava só `/auth /admin /bi ...`; faltava `/customers`. Adicionado ao `GATEWAY_MAPPING`: `path_prefix=/customers`, `strip_prefix=0`, `internal_url=http://platform-dataforall-admin:25987` (porta **não-padrão**), `public_paths=['/login','/register']`. **Requer restart do gateway** (registry lê o mapping no startup, `registry.py:18`). Backend valida `CUSTOMERS.password_hash` (bcrypt, `app.core.security`).
- **customer-admin (product-native, backend próprio):** o `/auth` global colide com platform-auth → não dá pra roteá-lo pelo gateway pro backend dele. Solução: rebuild do frontend com o **Dockerfile+nginx próprio** dele (imagem `:native`, porta 80) que proxia `/api`→`dataforall-customer-admin:8000` injetando `X-Tenant-Id` + `X-Internal-Token`. **O token é o `PLATFORMS[tenant].internal_token`** (o backend valida via `platform_auth.internal.require_internal_token` contra PLATFORMS — NÃO contra `settings.INTERNAL_API_TOKEN`). Passado no env do container (`INTERNAL_TOKEN`, lido do DB, não exibido). Migrations do serviço rodadas (tabela `accounts` + billing). Edge encaminha tudo → container:80.
- **partners (unificado):** o backend `platform-sales-partners` **não tem rota de login** — `spa_partner_users.password_hash` só é escrito no aceite de convite, e todo `/api/v1/*` exige JWT RS256 já emitido pelo platform-auth. Implementar o login exigiria mexer no platform-auth (core) p/ emitir RS256 com `partner_id` + mudar o front. Optou-se por **unificar**: frontend `partnerLogin.path` → `/auth/login` + parsing do token com fallback (`access_token`). Usa `adm_users`. `partner_id`/`partner_name` ficam `undefined` (usuário platform, sem escopo de parceiro) — páginas partner-específicas podem degradar; login e navegação básica OK. Commit no repo: `platform-sales-partners-frontend@2f1f9b8`.

## Seeds (rodar no box; a senha é sua)

```bash
# admin -> CUSTOMERS (bcrypt)
bash /opt/dataforall/deploy/seed/seed-admin-customer.sh   admin@data4all.com.br '<senha>'
# customer-admin -> accounts (Argon2id)
bash /opt/dataforall/deploy/seed/seed-customer-account.sh admin@platform.d4all.com.br '<senha>'
# sales/partners -> adm_users (ja seedado via seed-superadmin.sh p/ os tenants SALES e PARTNERS)
```

## Arquitetura real de auth (descoberta no debug do partner, 2026-07-07)

`/auth/login` (adm_users): o **platform-auth NÃO verifica a senha** — ele resolve o tenant por Host (DB = `tenant_id`; **não há coluna `db_name` na PLATFORMS**, o nome do schema = tenant_id) e **delega ao platform-admin** via `POST http://platform-admin:8000/api/internal/auth`. O platform-admin lê `<tenant>.adm_users` e verifica com `app.core.password.verify_password` (**Argon2id**, argon2-cffi; migra BLAKE2B legado). Campo canônico do body = **`identifier`** (mas `email` também é aceito → chega na verificação). Sucesso → `POST platform-admin/api/internal/iam/users/{id}/events/login 202` + `audit auth.login`. Falha → `.../api/internal/auth 401` + `audit auth.login_failed`. Logs em `docker logs platform-auth` (container **`platform-auth`**, não `platform-auth-mcp`). Colunas-chave de `adm_users`: `username,password,email,idf_access_profile,status,is_active` — o hash está em **`password`**, NÃO `password_hash`.

## Bug do seed (partner login 401) + reset

Partner dava **401** com conta válida e idêntica ao sales (mesmo argon2id, `status=active`, `is_active=1`). Causa: `seed-superadmin.sh` interpolava a senha **inline** no `python -c "...hash_password('$UPASS')"` → `$`/backtick/`\` na senha eram expandidos pelo **shell** antes do Python → hasheou uma string diferente da senha real → login com a senha certa dá 401. O sales não tinha caractere especial e por isso passou. **Corrigido** nos 3 seeds (senha via `docker exec -e SEED_PW` + `os.environ`). Como o seed é idempotente (não sobrescreve), criado **`deploy/seed/reset-superadmin-pass.sh`** (UPDATE do hash; senha via env, segura p/ qualquer char) — deployado em `/opt/dataforall/deploy/seed/`. Reset = ação do usuário (senha dele):
```bash
bash /opt/dataforall/deploy/seed/reset-superadmin-pass.sh PLATFORM_DATAFORALL_PARTNERS admin@partner.data4all.com.br 'NovaSenha'
```

## Bônus
- **platform-marketing** (`:2244` → 502) estava `Exited (0)`: religado (`docker compose up -d`) + corrigida a rota `GATEWAY_MAPPING` `/marketing` de `http://localhost:2244` → `http://platform-marketing:8000`. **Rotas `localhost:PORT` legadas ainda erradas** (mesmo padrão): `/marketing-agent`, `/agent`, `/crm`, `/monitoring` → corrigir p/ `http://<container>:8000` + restart do gateway se/quando esses widgets forem necessários.
