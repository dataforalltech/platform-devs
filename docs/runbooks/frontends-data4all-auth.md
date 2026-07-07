# Auth dos 4 frontends de produto (.com.br) — integração HML

**Data:** 2026-07-07. Complementa [frontends-data4all-bringup.md](frontends-data4all-bringup.md).

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

## Bônus
- **platform-marketing** (`:2244` → 502) estava `Exited (0)`: religado (`docker compose up -d`) + corrigida a rota `GATEWAY_MAPPING` `/marketing` de `http://localhost:2244` → `http://platform-marketing:8000`. **Rotas `localhost:PORT` legadas ainda erradas** (mesmo padrão): `/marketing-agent`, `/agent`, `/crm`, `/monitoring` → corrigir p/ `http://<container>:8000` + restart do gateway se/quando esses widgets forem necessários.
