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

1. ✅ **Cloudflare — FEITO via API (2026-07-07).** As 3 zonas (`data4all.com.br` `b4f5da6a…37e33`, `d4all.com.br` `2793a536…49c0e`, `dataforall.tech`) estão na conta `8a10daf8…65ed4`. No tunnel `dataforall-hml` (`17ea08ca-59c4-45be-a7e1-e5e37bdfe2a1`) foram adicionados 4 `ingress_rule` (`admin`/`partner`/`sales`.data4all.com.br + `platform.d4all.com.br` → `http://localhost:8080`), **preservando** o `*.dataforall.tech`. DNS (CNAME proxied → `<tunnel>.cfargotunnel.com`): admin/partner/sales criados; **`platform.d4all.com.br` repontado** (era `A 185.158.133.1`, não-proxied — guardar p/ revert). **Os 4 respondem `200` públicos via Cloudflare** com o app correto.

   **⚠️ Drift de Terraform.** A mudança foi via API. O `tunnel.tf` foi atualizado com os 4 `ingress_rule` (evita que um apply reverta o ingress — o resource do config já está no state, então sem `import`). As 4 CNAMEs **não** estão no state — para IaC completo, declare + `import` (NUNCA `terraform apply` amplo: `data.aws_ami.ubuntu` com `most_recent=true` pode **recriar a EC2 e perder o box**; use `-target` + `plan` revisado):

   ```hcl
   locals { cf_tunnel_cname = "${cloudflare_zero_trust_tunnel_cloudflared.main.id}.cfargotunnel.com" }
   resource "cloudflare_record" "admin_data4all"   { zone_id = "b4f5da6a2cb4c9b123521516ccb37e33" name = "admin"    type = "CNAME" value = local.cf_tunnel_cname proxied = true ttl = 1 }
   resource "cloudflare_record" "partner_data4all" { zone_id = "b4f5da6a2cb4c9b123521516ccb37e33" name = "partner"  type = "CNAME" value = local.cf_tunnel_cname proxied = true ttl = 1 }
   resource "cloudflare_record" "sales_data4all"   { zone_id = "b4f5da6a2cb4c9b123521516ccb37e33" name = "sales"    type = "CNAME" value = local.cf_tunnel_cname proxied = true ttl = 1 }
   resource "cloudflare_record" "platform_d4all"   { zone_id = "2793a53609cc8977b4585c0cc4049c0e" name = "platform" type = "CNAME" value = local.cf_tunnel_cname proxied = true ttl = 1 }
   ```
   ```bash
   terraform import cloudflare_record.admin_data4all   b4f5da6a2cb4c9b123521516ccb37e33/eb8b3ca624fb495851ad555b20b387c0
   terraform import cloudflare_record.partner_data4all b4f5da6a2cb4c9b123521516ccb37e33/e681b49a693f76f32b5c6a28f78672db
   terraform import cloudflare_record.sales_data4all   b4f5da6a2cb4c9b123521516ccb37e33/6a96249eb4fd6b453ae93c848f573eee
   terraform import cloudflare_record.platform_d4all   2793a53609cc8977b4585c0cc4049c0e/26a4c2f7380607170022dee074b8370a
   ```
   Reverter o `platform.d4all.com.br`: PUT a record `26a4c2f7…8370a` de volta p/ `A 185.158.133.1` (proxied=false).
2. **Superadmin por tenant (criação de conta):** cada tenant precisa de um usuário. Opções: auto-cadastro pela tela, **ou** `onboard-tenant.sh <tenant_id> <email> <senha>` (passo 4 — cria `adm_users_profile`/`adm_users`/`adm_users_login_config` com hash real). Ex.: `onboard-tenant.sh PLATFORM_DATAFORALL_ADMIN admin@... 'Senha!'`.
3. **CSP:** deixei `connect-src https: wss:` amplo nos 4 (bring-up seguro); apertar após smoke-test no browser (padrão do F3 no `pentest-frontends-2026-07.md`).
4. **customer-admin:** buildado como SPA gateway-único; tem um `nginx.conf.template` próprio (proxy a backend + injeção de token por-tenant) não usado. Reavaliar se o modelo dele deve ser esse.

## Comandos de referência
- Build: `deploy/build/build-frontend.sh <repo> <branch> <image>` (on-box).
- Reaplicar edge: editar `deploy/frontend/nginx.conf` → validar em container efêmero (`--network platform-local --add-host host.docker.internal:host-gateway`) → regenerar template + `nginx -s reload`.
- Onboarding infra (sem superadmin): CREATE DATABASE + `alembic -x tenant_id=.. -x db_host=tenant-mysql -x db_name=.. upgrade head` em cada serviço com estado.
