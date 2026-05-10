# platform-devs

MCP (Model Context Protocol) servers for the dataforalltech platform infrastructure.

This repository contains 18 operational MCP servers (12 infrastructure + 6 service) that provide tools for AI agents to interact with platform services, CI/CD systems, governance, and infrastructure management. **Phase 5 consolidation complete** (2026-05-09).

## Purpose

The platform-devs repository is the single source of truth for all MCP servers supporting the dataforalltech platform ecosystem. These servers are complementary to the `platform-service-template` (which remains a reference/scaffold for building Core Services following the Trinity Pattern).

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
5. **deploy-mcp-server** — GitHub operations (commits, PRs, workflows, ACR, deployments)
6. **agent-twin-mcp-server** — User/tenant context management and authentication
7. **docs-mcp-server** — Documentation validation, audit, and generation
8. **pipeline-mcp-server** — CI/CD pipeline orchestration and promotion gates
9. **qa-mcp-server** — Testing, linting, type checking, security, accessibility
10. **infra-mcp-server** — Infrastructure: Terraform, cost estimation, VM provisioning
11. **ai-governance-mcp-server** — Governance policies, decision validation, ecosystem rules
12. **audit-mcp-server** — Audit logging and compliance tracking

### Service Servers (6)

Located in `services/` subdirectory, consolidating MCP servers from platform services:

1. **auth-mcp-server** — JWT, OIDC, token management (from platform-auth)
2. **admin-mcp-server** — Admin operations and dashboards (from platform-admin)
3. **governance-mcp-server** — Governance workflows (from platform-governance)
4. **scheduler-mcp-server** — Job scheduling and orchestration (from platform-scheduler)
5. **connectors-mcp-server** — External integrations (from platform-connectors)
6. **cache-mcp-server** — Cache operations and management (from platform-cache)

## Central Configuration

All MCPs are registered in the central `.mcp.json` file:
- **Location:** `/home/dev/repos/platform-service-template/.mcp.json`
- **Entries:** 18 MCPs with absolute paths to servers
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

All 18 servers (via GitHub Actions):
```bash
# Trigger: .github/workflows/test-all-mcps.yml
# Tests 12 infra MCPs and 6 service MCPs in parallel
# Enforces 80% code coverage minimum
```

Individual server:
```bash
cd <server-name>
pytest tests/ -v --cov=src --cov-report=term-missing
```

### CI/CD

The `.github/workflows/` directory contains:
- `ci.yml` — Lint and test infrastructure servers on every PR
- `test-all-mcps.yml` — Complete testing matrix for all 18 MCPs (parallel)
  - Infrastructure MCPs: 12 parallel jobs
  - Service MCPs: 6 parallel jobs
  - Coverage validation: >= 80% per MCP
  - Artifact collection: coverage.json per MCP
- `ai-governance-mcp-ci.yml` — Governance-specific CI pipeline
- `ai-governance-mcp-release.yml` — Automated release management

## Documentation

- [docs/mcp-consolidation-complete.md](./docs/mcp-consolidation-complete.md) — Phase 5 milestone and consolidation summary
- [docs/mcp-discovery.md](./docs/mcp-discovery.md) — How to discover and use MCPs
- [.github/workflows/test-all-mcps.yml](./.github/workflows/test-all-mcps.yml) — Unified testing workflow

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
