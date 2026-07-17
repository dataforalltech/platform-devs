# platform-devs

MCP (Model Context Protocol) servers do **DevTeam** da plataforma dataforalltech — personas-especialistas + servers de papel (infra/qa/deploy/governança) que dão ferramentas a agentes de IA.

> **Escopo (revisado 2026-07-09):** a camada de **infra/deploy** (terraform, docker-compose HML, seeds, runbooks operacionais) foi migrada para [`platform-infra`](https://github.com/dataforalltech/platform-infra). Os **sidecars MCP de serviço** (analytics/ml/monitor/datalake/dataquality/dai/…) foram removidos — a fonte canônica é o `mcp/` de cada repo `platform-*`. Este repo mantém os MCP servers do DevTeam.

## Purpose

O `platform-devs` hospeda os MCP servers do **DevTeam**: as personas (architecture, backend, frontend, devops, product-owner, product-manager, qa-engineer, security) e os servers de papel/infra (session, test, config, services, deploy, dev-twin, docs, pipeline, qa, infra, ai-governance, audit), além de `mcp-gateway/`, `platform-catalog/` e `knowledge-base-mcp/`. O **runtime autônomo** (Modo B — planner→approval→executor) foi extraído para o repo standalone [`platform-devs-agent`](https://github.com/dataforalltech/platform-devs-agent) (pacote `app/devs_agent`) e **não** vive mais aqui como subdiretório. Este repo também **não** é mais o dono da infra/deploy (ver [`platform-infra`](https://github.com/dataforalltech/platform-infra)) nem dos sidecars de serviço (ver `platform-<x>/mcp`).

## Architecture

Each MCP server follows the Trinity Pattern:
- **MCP Server**: Stdio-based protocol handler for Claude and other AI agents
- **REST API**: Service interfaces for AI tool execution  
- **Configuration**: Environment-based settings management

### Infrastructure Servers (12)

Located in repository root, accessible via central `.mcp.json`:

1. **session-mcp-server** — Session tracking, checkpoints, and task management
2. **test-mcp-server** — Test planning, scenario generation, and result recording
3. **config-mcp-server** — Centralized configuration, environment variables, credentials
4. **services-mcp-server** — Service registry, health checks, service monitoring
5. **deploy-mcp-server** — Git/PR, ACR direto, workspace e ledger histórico; sem GitHub Actions
6. **dev-twin-mcp-server** — User/tenant context management and authentication
7. **docs-mcp-server** — Documentation validation, audit, and generation
8. **pipeline-mcp-server** — plano de controle de gates/promoções; não executa CI/CD
9. **qa-mcp-server** — Testing, linting, type checking, security, accessibility
10. **infra-mcp-server** — Infrastructure: Terraform, cost estimation, VM provisioning
11. **ai-governance-mcp-server** — Governance policies, decision validation, ecosystem rules
12. **audit-mcp-server** — Audit logging and compliance tracking

### services/ (sidecars de serviço)

Os sidecars que espelhavam um serviço (`admin`, `analytics`, `auth`, `connectors`, `dai`, `datalake`, `dataquality`, `governance`, `ml`, `monitor`, `pipeline`, `scheduler`) foram **removidos** — eram snapshots stale da Phase 5; a fonte canônica é o `mcp/` de cada repo `platform-<x>`. Permanece apenas **`cache-mcp-server`** (não há repo `platform-cache` correspondente).

## Central Configuration

Os servers do DevTeam são registrados no `.mcp.json` na raiz deste repo:
- **Entries:** 8 personas (paths relativos a `./`)
- **Used by:** Claude Code for unified MCP discovery and tool invocation

See [docs/mcp-discovery.md](./docs/mcp-discovery.md) for full discovery reference.

## Development

### Installation

Individual server (from its directory):
```bash
cd <server-name>
pip install -e ".[dev]"
```

### Running Tests

GitHub Actions foi aposentado. Até existir executor central aprovado, execute e
retenha os resultados em host controlado, vinculados ao commit.

Individual server:
```bash
cd <server-name>
pytest tests/ -v --cov=src --cov-report=term-missing
```

### Entrega

Não existe CI/CD automático comprovado neste repo. `pipeline-mcp` registra gates,
aprovações e promoções; os comandos são executados pelo processo manual controlado
definido em `platform-infra/docs/architecture/delivery-without-github-actions.md`.

## Documentation

- [docs/mcp-consolidation-complete.md](./docs/mcp-consolidation-complete.md) — Phase 5 milestone and consolidation summary
- [docs/mcp-discovery.md](./docs/mcp-discovery.md) — How to discover and use MCPs

## Related Resources

- **platform-service-template** — Scaffold and guidelines for new Core Services (Trinity Pattern)
- **AGENTS.md** — Universal governance policies for the dataforalltech platform
- **docs/architecture/trinity-pattern.md** — Architecture guidelines for MCP servers

## Health and Monitoring

All MCPs can be registered and monitored via `services-mcp`:

```python
# Register an MCP for monitoring
mcp__services-mcp__register_service(
    name="session-mcp",
    port=7090,
    url="http://localhost:7090"
)

# Check health
mcp__services-mcp__check_health(name="session-mcp")

# Check all
mcp__services-mcp__check_all_health()
```

## Phase 5 Completion

**Date:** 2026-05-09  
**Status:** COMPLETE

- All 18 MCPs consolidated in platform-devs
- Central .mcp.json configuration created
- CI/CD workflow activated (test-all-mcps.yml)
- Documentation complete
- Coverage validation: 80% minimum per MCP
- Next: Run full test suite, verify all MCPs pass coverage threshold

## License

Proprietary — dataforalltech
