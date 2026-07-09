# Índice da documentação — platform-devs

Mapa de navegação dos documentos **vivos**. Snapshots históricos ficam em
**[archive/](archive/README.md)**. Última organização: **2026-07-08**.

---

## 🔐 Contrato de auth (atual — pós-remediação de segurança, jul/2026)

Referência rápida do modelo vigente. Detalhe operacional nos runbooks abaixo.

- **Fluxo externo (usuário):** `frontend → edge nginx → gateway :9999` (resolve tenant pelo `Host`) `→ serviço`, em `/api/v1/*` com **JWT de usuário** (`require_auth` + role). Continua válido.
- **S2S (serviço → platform-admin):** via `http://platform-admin:8000/api/internal/*` + header `X-Internal-Token` (por-tenant), autorizado por `require_internal_token` (**GW-18**). O `X-Internal-Token` **não** autoriza mais `/api/v1/*` (bypass removido — **PP-04**).
- **Login:** `platform-auth` delega o check de senha para `POST /api/internal/auth` (`URL_ADMIN`/`URL_IAM = .../api/internal`).
- **Demais S2S callers** (`customer-admin`, `analytics`, `notification`, `crm`, `platform-admin` self): `URL_IAM → /api/internal/iam`.
- **Operadores admin** (`platform-dataforall-admin`): **RS256** via `platform_auth.jwt_manager` (JWKS do `platform-auth`, `aud=platform-services`, `kid=platform-auth-1`).
- **Isolamento por tenant (H1):** tabelas legadas de IAM/domínio têm `tenant_id` (NOT NULL, backfilled).
- **MCP admin:** alcança o admin via `/api/internal/*`; tools *guarded* = **fail-closed** (Twin Token PEP).
- **Mitigação de borda:** nginx retorna 404 em `/api/v1/(admin|bi|twins|governance|monitoring)` nos domínios de produto.

Runbooks relacionados: [frontends-data4all-auth](runbooks/frontends-data4all-auth.md) · [environment-variables](runbooks/environment-variables.md) · [bring-up-errors-and-fixes](runbooks/bring-up-errors-and-fixes.md)

---

## 🏛️ Arquitetura & Decisões (ADRs)

- **ADRs:** [ADR-001](../ADR-001-PYTHON-POSTGRESQL-MIGRATION.md) … [ADR-016](../ADR-016-CI-VALIDATION-STRATEGY.md) (raiz) · índice: [MCP_ADR_INDEX](../MCP_ADR_INDEX.md)
- **Stack oficial:** [docs/architecture/official-stack-and-architecture](architecture/official-stack-and-architecture.md)
- **Serviços HTTP / perfis:** [ARCHITECTURE_HTTP_SERVICES](../ARCHITECTURE_HTTP_SERVICES.md) · [ARCHITECTURE_PROFILES_WORKFLOWS](../ARCHITECTURE_PROFILES_WORKFLOWS.md) · [ARCHITECTURE_ANALYSIS_INDEX](../ARCHITECTURE_ANALYSIS_INDEX.md)
- **Visão geral / tags:** [docs/OVERVIEW](OVERVIEW.md) · [docs/TAGGING](TAGGING.md)

## 📕 Runbooks operacionais (`docs/runbooks/`)

- **Bring-up:** [bring-up-from-scratch](runbooks/bring-up-from-scratch.md) · [bring-up-errors-and-fixes](runbooks/bring-up-errors-and-fixes.md) · [frontends-data4all-bringup](runbooks/frontends-data4all-bringup.md)
- **Auth / frontends:** [frontends-data4all-auth](runbooks/frontends-data4all-auth.md)
- **Config:** [environment-variables](runbooks/environment-variables.md)
- **Deploy prod:** [aws-production-deployment-playbook](runbooks/aws-production-deployment-playbook.md) · [HANDOFF](runbooks/HANDOFF.md)
- **DB / infra:** [local-db-access-ssm](runbooks/local-db-access-ssm.md) · [mysql-volume-migration](runbooks/mysql-volume-migration.md)
- **MCP backends:** [register-mcp-backends](runbooks/register-mcp-backends.md)

## 🚀 Deploy, Gateway & CI

- [DEPLOYMENT_GUIDE](../DEPLOYMENT_GUIDE.md) · [GATEWAY_QUICK_START](../GATEWAY_QUICK_START.md) · [CI_CD_README](../CI_CD_README.md)

## 🧩 MCP (construção & catálogo)

- [MCP_CONSTRUCTION_GUIDE](../MCP_CONSTRUCTION_GUIDE.md) · [MCP_CONVERSION_PATTERN](../MCP_CONVERSION_PATTERN.md) · [MCP_FASTAPI_DOCKER](../MCP_FASTAPI_DOCKER.md)
- [docs/mcp-discovery](mcp-discovery.md) · [docs/mcp-healthcheck-standard](mcp-healthcheck-standard.md)
- **Twin PEP (autz):** [MCP_PHASE1_TWINPEP_MIGRATION](../MCP_PHASE1_TWINPEP_MIGRATION.md) · **Frontdoor OAuth:** [MCP_OAUTH_FRONTDOOR_DESIGN](../MCP_OAUTH_FRONTDOOR_DESIGN.md)

## 📊 Dashboards & Roadmaps (vivos)

- [SERVICES_DASHBOARD](../SERVICES_DASHBOARD.md) · [REPOS_STATUS_DASHBOARD](../REPOS_STATUS_DASHBOARD.md) · [ORCHESTRATION](../ORCHESTRATION.md)
- [DEVTEAM_ECOSYSTEM_SUMMARY](../DEVTEAM_ECOSYSTEM_SUMMARY.md) · [DEVTEAM_ECOSYSTEM_IMPLEMENTATION_ROADMAP](../DEVTEAM_ECOSYSTEM_IMPLEMENTATION_ROADMAP.md)

## 🛡️ Segurança / Pentest

- **📌 Consolidado (jul/2026):** [remediation-2026-07-consolidated](runbooks/remediation-2026-07-consolidated.md) — registro profundo (C1/F02/S2S/H1/RS256/M3/console de parceiro) · **[HANDOFF-2026-07-remediation](runbooks/HANDOFF-2026-07-remediation.md)** — passagem de bastão
- **Remediação F02 (auth/S2S):** [f02-auth-s2s-remediation](runbooks/f02-auth-s2s-remediation.md) — o quê/porquê/contrato/PRs/validação/pendências
- [pentest-frontends-2026-07](runbooks/pentest-frontends-2026-07.md) · [pentest-frontends-source-2026-07](runbooks/pentest-frontends-source-2026-07.md)
- Contrato de auth vigente: ver a seção **🔐 Contrato de auth** no topo.

## 🤖 Agentes

- [AGENTS](../AGENTS.md) · [PLATFORM_DEV_AGENT_SPEC](../PLATFORM_DEV_AGENT_SPEC.md)

---

## 🗄️ Histórico arquivado

Snapshots e relatórios de conclusão (migração DevTeam/MCP, auditorias 2026-05) →
**[docs/archive/](archive/README.md)** (31 documentos, movidos via `git mv`).
