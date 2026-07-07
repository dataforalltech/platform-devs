# Bring-up dos frontends de produto (.com.br) na VM HML

**Data:** 2026-07-07 · **VM:** `i-002379444ffb89c10` · **Edge:** container `dataforall-frontend` (nginx, `127.0.0.1:8080` ← tunnel Cloudflare).

Subida dos 4 frontends de produto na VM HML, com onboarding de tenant (DB + migrations) e roteamento no edge. Complementa [pentest-frontends-source-2026-07.md](pentest-frontends-source-2026-07.md) (a revisão de segurança destes mesmos repos).

## 1. Mapa completo (repo → imagem → container → domínio → tenant → DB)

| Frontend (repo GitHub `dataforalltech/`) | Branch | Imagem `d4all.azurecr.io/dataforall/3.0/` | Container | Domínio | `tenant_id` (PLATFORMS id) | DB (`tenant-mysql`) |
|---|---|---|---|---|---|---|
| platform-dataforall-admin-frontend | master | admin-data4all-frontend | admin-data4all-frontend | admin.data4all.com.br | PLATFORM_DATAFORALL_ADMIN (4) | PLATFORM_DATAFORALL_ADMIN |
| dataforall-customer-admin-frontend | develop | platform-d4all-frontend | platform-d4all-frontend | platform.d4all.com.br | PLATFORM_DATAFORALL_CUSTOMER_ADMIN (5) | PLATFORM_DATAFORALL_CUSTOMER_ADMIN |
| platform-sales-partners-frontend | develop | partner-data4all-frontend | partner-data4all-frontend | partner.data4all.com.br | PLATFORM_DATAFORALL_PARTNERS (6) | PLATFORM_DATAFORALL_PARTNERS |
| dataforall-sales-frontend | develop | sales-data4all-frontend | sales-data4all-frontend | sales.data4all.com.br | PLATFORM_DATAFORALL_SALES (7) | PLATFORM_DATAFORALL_SALES |

Arquitetura: **gateway-único** — o SPA chama `origin + /api/v1`; o edge proxia `/api` → gateway `host.docker.internal:9999`, que resolve o **tenant pelo `Host`** (via `ADMIN_DATAFORALL.PLATFORMS`) e roteia por path (GATEWAY_MAPPING, compartilhado). Tenant DBs ficam em `tenant-mysql`.

## 2. O que foi feito

1. **Build on-box** (`deploy/build/build-frontend.sh`, sem push): clona o repo, injeta Dockerfile multi-stage (node:22 build → nginx:1.27-alpine) + nginx enxuto (SPA-only), builda com tag ACR local. Imagens ~74–93 MB.
2. **Containers** no `platform-local` (`deploy/frontend/docker-compose.data4all.yml`), `restart: unless-stopped`.
3. **Edge routing** (`deploy/frontend/nginx.conf`): 4 server blocks `.com.br` com security headers (CSP/HSTS/XFO/nosniff/Referrer/Permissions/COOP/CORP), gate anti-bot, rate-limit, `/api`+`/ws`→gateway :9999, `/`→SPA. Aplicado com validação em container efêmero + reload zero-downtime.
4. **PLATFORMS** (`ADMIN_DATAFORALL.PLATFORMS`): 4 linhas (ids 4–7) inseridas via `INSERT..SELECT` copiando `internal_token`/`db_password` da linha `dataforall` (segredos corretos, `db_host=tenant-mysql`, `active=1`).
5. **Onboarding de tenant** (DB + migrations, mirror do `onboard-tenant.sh` 1–3b, **sem** o superadmin): DB criado em `tenant-mysql` + migrations de platform-admin (20), platform-auth (8), governance (33), notification (0), connectors (71), analytics (16), communication (28) — **0 erros, 174 tabelas/tenant**.

## 3. Verificação (via edge, `Host:` header)

- SPA: os 4 → `200` + título correto (`Dataforall Admin` / `Portal do Cliente` / `Console do Parceiro` / `Plataforma Interna`), 4/4 security headers, assets ok.
- `/api/v1/auth/login` (body vazio): os 4 → **`422` "Field required"** (tenant resolve, DB ok, auth valida). Antes das linhas: `UNKNOWN_DOMAIN 403`; após linha sem DB: `500`; após onboarding: `422`. ✅
- Regressão `.tech`: app `200`, sales `503`, partner `200` — intactos.

## 4. Pendências para 100%

1. **Cloudflare Tunnel (fora do box — dashboard/API):** o tunnel é gerenciado por token; adicionar 4 *public hostnames* em **Zero Trust → Networks → Tunnels → [tunnel] → Public Hostname**, cada um → **Service HTTP `localhost:8080`**, para `admin.data4all.com.br`, `platform.d4all.com.br`, `partner.data4all.com.br`, `sales.data4all.com.br`. Cria o DNS e leva o tráfego ao box. (Pré-req: domínios na mesma conta Cloudflare.)
2. **Superadmin por tenant (criação de conta):** cada tenant precisa de um usuário. Opções: auto-cadastro pela tela, **ou** `onboard-tenant.sh <tenant_id> <email> <senha>` (passo 4 — cria `adm_users_profile`/`adm_users`/`adm_users_login_config` com hash real). Ex.: `onboard-tenant.sh PLATFORM_DATAFORALL_ADMIN admin@... 'Senha!'`.
3. **CSP:** deixei `connect-src https: wss:` amplo nos 4 (bring-up seguro); apertar após smoke-test no browser (padrão do F3 no `pentest-frontends-2026-07.md`).
4. **customer-admin:** buildado como SPA gateway-único; tem um `nginx.conf.template` próprio (proxy a backend + injeção de token por-tenant) não usado. Reavaliar se o modelo dele deve ser esse.

## Comandos de referência
- Build: `deploy/build/build-frontend.sh <repo> <branch> <image>` (on-box).
- Reaplicar edge: editar `deploy/frontend/nginx.conf` → validar em container efêmero (`--network platform-local --add-host host.docker.internal:host-gateway`) → regenerar template + `nginx -s reload`.
- Onboarding infra (sem superadmin): CREATE DATABASE + `alembic -x tenant_id=.. -x db_host=tenant-mysql -x db_name=.. upgrade head` em cada serviço com estado.
