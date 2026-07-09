# Remediação de Segurança + Console de Parceiro — Consolidado (jul/2026)

**Período:** 2026-07-07 a 2026-07-09 · **Ambiente:** HML (EC2 `i-002379444ffb89c10`, acesso só via AWS SSM) · **Escopo:** pentest autenticado dos 4 frontends `.com.br` + gateway/auth/admin → remediação completa → cabeamento do Console de Parceiro.

> Este é o registro **profundo**. Referências rápidas: [f02-auth-s2s-remediation](f02-auth-s2s-remediation.md), [../INDEX.md](../INDEX.md), [frontends-data4all-auth](frontends-data4all-auth.md).

---

## Sumário executivo

Um pentest autenticado revelou um **crítico internet-facing (C1)**: qualquer um sem credencial lia/escrevia o CRUD do `platform-admin` nos domínios de produto. A remediação (F02) removeu o bypass e migrou o S2S para `/api/internal/*` — o que se revelou uma **breaking change do tecido S2S de IAM inteiro**, exigindo repontar **todos** os chamadores. Em seguida, corrigimos o isolamento por tenant (H1), o RS256 dos operadores/cliente, e implementamos o **M3** (claim `partner_id`). Por fim, completamos o **Console de Parceiro**, que estava incompletamente cabeado em **6 camadas**. Tudo mergeado na `develop` dos repos e validado no HML.

---

## 1. C1 — bypass de autenticação (CRÍTICO, internet-facing)

**Sintoma:** `curl` sem `Authorization`/cookie em `https://{partner,admin,sales}.data4all.com.br/api/v1/admin/domains` → **200**; POST sem auth → 422 (escrita autorizada); token lixo → 200 (assinatura nem checada). `platform.d4all` não (nginx próprio).

**Causa (2 elos):** (1) o `platform-api-gateway` injeta `X-Internal-Token` por-tenant em **toda** request (`proxy.py`) e roteia só por path; (2) o `platform-admin` tratava esse token como identidade de serviço confiável e **pulava JWT+role** (`internal_service_verified` + monkeypatch de `require_module_permission`). Tráfego de usuário proxiado herdava o bypass. Intencional para o sidecar MCP (handoff 28/06), vazou porque o gateway reusa o mesmo token no tráfego de usuário.

**Contenção imediata:** mitigação de borda no nginx — `location ~ ^/api/v1/(admin|bi|twins|governance|monitoring)(/|$) { return 404; }` nos domínios de produto (validado 200→404).

---

## 2. F02 — remediação na raiz

Contrato novo:

| Superfície | Autenticação |
|---|---|
| **Externo** (frontend → gateway → serviço) | `/api/v1/*` + **JWT de usuário** (`require_auth` + role) |
| **S2S** (serviço → platform-admin) | `/api/internal/*` + `X-Internal-Token` (`require_internal_token`) — **GW-18** |
| **Público** (SSO/SCIM/JWKS) | `V1_PUBLIC_ROUTERS` (sem JWT) |

- Bypass removido: `X-Internal-Token` **não** autoriza mais `/api/v1/*` (**PP-04**).
- `admin_mcp` reapontado (190 chamadas `/api/v1`→`/api/internal`) + forwarding do token.
- **Defeito pego no deploy:** o MCP deployado é `admin_mcp/` (não `mcp/`) — o F02 tinha reapontado o arquivo errado; corrigido antes de mergear.
- **Validado ao vivo:** `/api/v1/admin`+tok sem JWT=**401**, `/api/internal/admin`+tok=**200**/sem tok=**401**, JWKS=200.

## 3. Raio sistêmico S2S — todo caller do IAM precisou repontar

O F02 quebra o **login** e **todo** S2S de IAM: o `platform-auth` delegava o check de senha em `URL_ADMIN=/api/v1/auth` (contrato do bypass). Auditoria (cliente com `base_url=URL_IAM/URL_ADMIN` no `/api/v1`):

- **Quebravam → corrigidos:** platform-auth, platform-notification, platform-analytics, dataforall-customer-admin, platform-crm, platform-admin (self-call).
- **Safe:** gateway (proxia), connectors (JWKS público), agents-factory.

Fix: `URL_ADMIN`/`URL_IAM` → `/api/internal[/iam]` nos `config.py` (defaults) + composes de deploy. **Validado:** login via `platform-auth → POST /api/internal/auth`.

## 4. H1 — isolamento por tenant (BOLA cross-tenant)

Tabelas legadas de IAM/domínio (`adm_users`, `adm_domain`) sem `tenant_id` → BOLA. **Caso A:** cada tenant tem DB próprio (7 tenants), backfill trivial `SET tenant_id=<tenant do DB>`. Migrations **021** (add col nullable) → **022** (backfill) → verificar zero-NULL → **023** (estrito + NOT NULL, guarda). Validado nos 7 tenants.

## 5. RS256 — operadores + cliente

- **platform-dataforall-admin** (operador): HS256 → **RS256** via `platform_auth.jwt_manager` compartilhado.
- **dataforall-customer-admin** (cliente + parceiro): estava HS256 → "alg not allowed" nos tokens RS256 do platform-auth. Fix: `RS256` + `JWT_JWKS_URL` (JWKS do platform-auth) + `aud=platform-services` + **mount da chave de assinatura** `jwt-auth.pem`→`/run/secrets/jwt_key.pem` (o serviço EMITE tokens de cliente; JWKS cobre só verificação). **Chave = a do platform-auth, `kid=platform-auth-1`** — reusada por admin+customer-admin. **Sem tocar no platform-auth.**

## 6. M3 — claim `partner_id` (tabela de identidade externa)

Design (a pedido, tabela filha em vez de coluna): **`adm_user_external_link`** — `idf_user`, `external_id`, `external_source`, `tenant_id` (migration **024**, per-tenant). Polimórfica (extensível a qualquer fonte), não polui a identidade. O `/api/internal/auth` resolve o link `external_source='partner'` e devolve `partner_id`; o platform-auth **já** carrega o claim (0 mudança — plumbing pronto). **Refresh-proof:** o `require_partner` do customer-admin resolve o `partner_id` do link pelo `sub` quando o claim falta (o refresh do platform-auth não o re-emite).

## 7. Console de Parceiro — 6 camadas de cabeamento incompleto

`partner.data4all.com.br` dava *"Não foi possível carregar a visão geral"*. Não era 1 bug — eram 6 camadas (feature WIP). Diagnóstico só fechou com **logs em runtime** (`--tail`; o relógio do box estava adiantado, escondendo logs nas janelas `--since`).

| # | Camada | Fix |
|---|---|---|
| 1 | **Gateway route** `/api/v1/partner/*` ausente → 404 "No service registered" | INSERT no `GATEWAY_MAPPING` (`/partner`→customer-admin:8000, strip_prefix=0) + restart do gateway; seed durável `register-partner-gateway-route.sh` |
| 2 | **M3 `partner_id`** ausente no token | tabela `adm_user_external_link` + resolve no `/auth` |
| 3 | **Provisão** — tabelas de parceiro não existiam no tenant | `alembic upgrade head -x tenant_id=...` do customer-admin |
| 4 | **Parceiro real** — o user é o admin do tenant | seed `partners(id=1)` + link M3 |
| 5 | **RS256** — customer-admin em HS256 | ver §5 (RS256 + chave de assinatura) |
| 6 | **Refresh-proof** — claim perdido no refresh | `require_partner` async resolve do DB pelo `sub` |

**Resultado:** `/api/v1/partner/dashboard → 200`, console carrega (estados vazios corretos).

## 8. Limpeza `node_modules`

O repo `platform-devs` tinha **36.293 arquivos de `node_modules/` commitados (94% dos 38.396)** em 11 sub-projetos MCP Node/TS — nenhum `.gitignore` os excluía (buscas amplas davam timeout). Fix não-destrutivo: `node_modules/` no `.gitignore` + `git rm -r --cached` (preservado no disco). **38.396 → 2.103 arquivos rastreados; `.md` 6.546 → 202.** (PR #22)

## 9. Reorganização de docs

11 docs obsoletos atualizados pro contrato novo (via workflow de 16 agentes, respeitando externo≠interno); 31 snapshots históricos → `docs/archive/`; novo `docs/INDEX.md` (mapa + contrato de auth atual).

## 10. Deploy HML + imagens

- Build on-box via `build-service.sh <img> <repo> <branch>` (clona do GitHub + BuildKit + push ACR :latest+:sha). Fluxo `dtr-local` p/ o `admin-mcp` (FROM `platform-admin:dtr-local`).
- **CI da develop está VERMELHO (pré-existente — lint/scan/sast/secret-scan; `test` fica skipped)** → o pipeline `cd-dev` não produz `:develop-latest`. Por isso os builds foram on-box (autorizado).
- Imagens canônicas do develop rebuildadas + pushadas ao ACR (:latest+:sha): platform-admin(+mcp), platform-auth, platform-notification(+mcp), dataforall-customer-admin.

## 11. PRs mergeados na develop (sessão)

| Repo | PR/commit | Conteúdo |
|---|---|---|
| platform-admin | #59, #60 | F02 (bypass, /internal, H1, admin_mcp) + M3 |
| platform-auth | #25 | repoint S2S /internal |
| platform-notification | #53 + 3917ce5 | repoint + fix healthcheck do mcp |
| platform-api-gateway | #21 | M4 (verificação de assinatura) |
| platform-devs | #22, #23, +develop | limpeza node_modules + composes S2S/RS256 + docs + seeds |
| dataforall-customer-admin | #37 | refresh-proof (require_partner do DB) |
| platform-sales-partners-frontend | #5 | M2/M5 |
| dataforall-customer-admin-frontend | #3 | M2/M5 |
| platform-dataforall-admin | #5 | L2/M5/RS256 |

## 12. Pendências / follow-ups

- **CI da develop vermelho** (pré-existente, lint/scan) — bloqueia o pipeline automático; sanear pra `cd-dev` voltar. Posso diagnosticar.
- **crm** config.py default `/api/v1/iam` (repo não-local) — coberto pelo compose; repontar no repo.
- **RBAC-03** aud-por-serviço (operador reusa `aud=platform-services`, replayável) — diferido.
- **Console de parceiro**: os fixes de gateway/provisão/seed foram no HML (via seed/migration) — replicar em outros ambientes via o seed + as migrations no onboarding.
- **28 E2E do admin_mcp**: o arquivo testa `/mcp/tools/*` mas o servidor serve `/v1/*` (drift de teste) — reconciliar.

## 13. Lições

- O bypass do internal-token vazou por reuso no tráfego de usuário — S2S e user-traffic **nunca** devem compartilhar credencial de confiança.
- Diagnóstico de auth exige **logs em runtime**, não só leitura de código (o C1 foi rebaixado por um verificador que assumiu RBAC downstream — premissa falsa).
- Features "prontas" podem estar incompletamente cabeadas em várias camadas invisíveis (o console de parceiro).
