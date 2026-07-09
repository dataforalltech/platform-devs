# Índice da documentação — platform-devs (MCP servers do DevTeam)

Mapa dos documentos **vivos** deste repo (MCP servers, gateway, catalog, agente).
Snapshots históricos em **[archive/](archive/README.md)**. Última organização: **2026-07-09**.

> **Infra / deploy / ops migraram para [`platform-infra`](https://github.com/dataforalltech/platform-infra):**
> runbooks operacionais (bring-up, environment-variables, remediação de auth F02, pentests, HANDOFF),
> terraform(-lean), docker-compose HML, seeds, dashboards de deploy, ADR-002/015/016. Ver o README de lá.

---

## 🏛️ Arquitetura & Decisões (ADRs de MCP)

- **ADRs (MCP / capability / catalog):** [ADR-001](../ADR-001-PYTHON-POSTGRESQL-MIGRATION.md), [ADR-003](../ADR-003-MCP-IDENTITY.md) … [ADR-014](../ADR-014-ASSET-MODEL.md) (raiz) · índice: [MCP_ADR_INDEX](../MCP_ADR_INDEX.md)
- **Serviços HTTP / perfis:** [ARCHITECTURE_HTTP_SERVICES](../ARCHITECTURE_HTTP_SERVICES.md) · [ARCHITECTURE_PROFILES_WORKFLOWS](../ARCHITECTURE_PROFILES_WORKFLOWS.md) · [ARCHITECTURE_ANALYSIS_INDEX](../ARCHITECTURE_ANALYSIS_INDEX.md)

## 🧩 MCP (construção & catálogo)

- [MCP_CONSTRUCTION_GUIDE](../MCP_CONSTRUCTION_GUIDE.md) · [MCP_CONVERSION_PATTERN](../MCP_CONVERSION_PATTERN.md) · [MCP_FASTAPI_DOCKER](../MCP_FASTAPI_DOCKER.md)
- [docs/mcp-discovery](mcp-discovery.md) · [docs/mcp-healthcheck-standard](mcp-healthcheck-standard.md)
- **Twin PEP (autz):** [MCP_PHASE1_TWINPEP_MIGRATION](../MCP_PHASE1_TWINPEP_MIGRATION.md) · **Frontdoor OAuth:** [MCP_OAUTH_FRONTDOOR_DESIGN](../MCP_OAUTH_FRONTDOOR_DESIGN.md)
- **Gateway:** [GATEWAY_QUICK_START](../GATEWAY_QUICK_START.md) · **Registrar backends no gateway:** [register-mcp-backends](runbooks/register-mcp-backends.md)
- **Catálogo (gaps):** [docs/catalog-gaps/runbooks-wave1](catalog-gaps/runbooks-wave1.md) · **Decisão Trinity:** [docs/decisions/adr-0001](decisions/adr-0001.md)

## 🤖 DevTeam & Agentes

- [AGENTS](../AGENTS.md) · [PLATFORM_DEV_AGENT_SPEC](../PLATFORM_DEV_AGENT_SPEC.md) · [ORCHESTRATION](../ORCHESTRATION.md)
- [DEVTEAM_ECOSYSTEM_SUMMARY](../DEVTEAM_ECOSYSTEM_SUMMARY.md) · [DEVTEAM_ECOSYSTEM_IMPLEMENTATION_ROADMAP](../DEVTEAM_ECOSYSTEM_IMPLEMENTATION_ROADMAP.md)

## 🗄️ Histórico arquivado

Snapshots e relatórios de conclusão (migração DevTeam/MCP, auditorias 2026-05) →
**[docs/archive/](archive/README.md)**.
