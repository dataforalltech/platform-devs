# F02 — Remediação de auth / S2S (hardening pós-pentest)

**Status:** mergeado na `develop` dos 4 repos (2026-07-08). Gate final = CI build+deploy da develop.
**Contexto:** pentest autenticado dos 4 frontends `.com.br` + gateway/auth/admin (2026-07).

---

## 1. O que era o problema (C1 — crítico, internet-facing)

Qualquer um **sem credencial** lia e podia escrever o CRUD do **platform-admin**
(`/admin/*`, `/twins/*`) em `partner`/`admin`/`sales.data4all.com.br`, escopado ao tenant do domínio.

**Causa (2 elos):** (1) o gateway injeta `X-Internal-Token` por-tenant em **toda** request;
(2) o platform-admin tratava esse token como identidade de serviço confiável e **pulava JWT+role**
(`internal_service_verified` + monkeypatch de `require_module_permission`). Resultado: tráfego de
usuário proxiado herdava o bypass → acesso não autenticado ao `/api/v1/admin/*`.

## 2. O contrato novo (vigente pós-F02)

| Superfície | Como autentica |
|---|---|
| **Externo** (frontend → gateway → serviço) | `/api/v1/*` com **JWT de usuário** (`require_auth` + role) |
| **S2S** (serviço → platform-admin) | `/api/internal/*` + `X-Internal-Token` por-tenant (`require_internal_token`) — **GW-18** |
| **Público** (SSO/SCIM/JWKS) | `V1_PUBLIC_ROUTERS` (sem JWT) |

- O `X-Internal-Token` **não autoriza mais** `/api/v1/*` (bypass removido — **PP-04**).
- **Login:** platform-auth delega o check de senha para `POST /api/internal/auth`.
- **S2S IAM:** os callers usam `URL_IAM = .../api/internal/iam`.
- **Operadores admin** (platform-dataforall-admin): HS256 → **RS256** via `platform_auth.jwt_manager`
  (JWKS do platform-auth, `aud=platform-services`, `kid=platform-auth-1`).
- **H1 (isolamento por tenant):** tabelas legadas de IAM/domínio ganharam `tenant_id`
  (NOT NULL, backfilled — migrations 021→022→023).
- **MCP admin:** alcança o admin via `/api/internal/*`; tools *guarded* = **fail-closed** (Twin Token PEP).
- **Mitigação de borda (interina):** nginx retorna 404 em
  `/api/v1/(admin|bi|twins|governance|monitoring)` nos domínios de produto — contém o C1 até o deploy do F02.

## 3. Raio sistêmico — todo caller S2S do IAM precisou repontar

O F02 é uma breaking change do **tecido S2S de IAM inteiro**, não só do login. Todo serviço que
fazia S2S direto no `/api/v1/iam` do platform-admin com `X-Internal-Token` passou a repontar:

- **Quebravam → corrigidos:** platform-auth, platform-notification, platform-analytics,
  dataforall-customer-admin, platform-crm, platform-admin (self-call).
- **Safe (sem client S2S no /api/v1):** gateway (proxia), platform-connectors (JWKS público),
  platform-agents-factory, demais sem `URL_IAM`.

Operacionalmente o repoint vive nos **composes de deploy** (`platform-devs/deploy/services/*`), que
sobrescrevem o `URL_IAM`/`URL_ADMIN` de cada serviço → `/api/internal[/iam]`.

## 4. Repos / PRs (mergeados na develop, 2026-07-08)

| Repo | PR | Mudança |
|---|---|---|
| platform-admin | **#59** | F02: bypass removido, `/api/internal` mirror, admin_mcp repontado, migrations H1 |
| platform-auth | #25 | `URL_ADMIN`/`URL_IAM` → `/api/internal` |
| platform-notification | #53 | config.py `URL_IAM` → `/api/internal/iam` |
| platform-devs | #23 | 11 composes → `/api/internal` + docs (INDEX/archive) |

**Ordem de merge/deploy (obrigatória):** platform-admin (F02) **primeiro** — é quem cria o
`/api/internal`. Deployar os repoints sem o F02 → serviços chamam `/api/internal` → 404 → quebra geral.

## 5. Validação (HML, live via SSM)

- `/api/v1/admin/*` + internal-token **sem JWT** → **401** (bypass removido) ✅
- `/api/internal/admin/*` + token → **200** / sem token → **401** ✅
- Login ponta-a-ponta: `platform-auth → POST /api/internal/auth → iam_auth.login` (usuário falso → 401 "Credenciais inválidas", não 5xx) ✅
- `/api/internal/iam/users` + token → **200** ✅
- H1: migrations rodaram nos 7 tenants (zero-NULL → NOT NULL) ✅
- MCP: guarded tools = DENY fail-closed sem Twin Token ✅

## 6. Pendências / ressalvas (para o time)

- **crm** config.py default (`/api/v1/iam`) — repo não-local; coberto pelo compose, mas repointar no repo.
- **analytics / platform-admin** config.py defaults são **via-gateway** (`/api/v1/admin`) — avaliar se também vão pra `/internal`.
- **RS256 admin:** conferir `JWT_KID`×`JWT_KEY_ID` no staging + publicação da chave no JWKS.
- **28 E2E do admin_mcp:** o arquivo testa `/mcp/tools/*` mas o servidor serve `/v1/*` — **drift de teste** a reconciliar (falharia no CI como está).
- **RBAC-03 (aud-por-serviço):** operador reusa `aud=platform-services` (replayável) — diferido.
- **Borda:** o 404 do nginx segue contendo o C1 até o deploy do F02 pela develop.

> Referência do contrato: [../INDEX.md](../INDEX.md#-contrato-de-auth-atual--pós-remediação-de-segurança-jul2026). Política canônica: Dataforall Hardening Standard v2.0.
