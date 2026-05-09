# platform-devs

MCP (Model Context Protocol) servers for the dataforalltech platform infrastructure.

This repository contains 11 operational MCP servers that provide tools for AI agents to interact with platform services, CI/CD systems, governance, and infrastructure management.

## Purpose

The platform-devs repository is dedicated to hosting all MCP servers that support the dataforalltech platform ecosystem. These servers are complementary to the `platform-service-template` (which remains a reference/scaffold for building Core Services following the Trinity Pattern).

## Architecture

Each MCP server follows the Trinity Pattern:
- **MCP Server**: Stdio-based protocol handler for Claude and other AI agents
- **REST API**: Service interfaces for AI tool execution  
- **Configuration**: Environment-based settings management

### Included Servers

1. **agent-twin-mcp-server** — User/tenant context management and authentication
2. **ai-governance-mcp-server** — Governance policies, validation, and ecosystem management
3. **config-mcp-server** — Centralized configuration and credential management
4. **deploy-mcp-server** — GitHub operations (commits, PRs, workflows, ACR image building)
5. **docs-mcp-server** — Documentation validation, audit, and generation
6. **infra-mcp-server** — Infrastructure and ADR management
7. **pipeline-mcp-server** — CI/CD pipeline orchestration
8. **qa-mcp-server** — Testing, linting, type checking, accessibility validation
9. **services-mcp-server** — Service registry and health monitoring
10. **session-mcp-server** — Session tracking and task management
11. **test-mcp-server** — Test planning and execution tools

## Development

### Installation

```bash
pip install -e .
```

### Running Tests

All 11 servers:
```bash
pytest
```

Individual server:
```bash
pytest <server-name>/tests/
```

### CI/CD

The `.github/workflows/` directory contains:
- `ci.yml` — Lint and test all servers on every PR
- `ai-governance-mcp-ci.yml` — Governance-specific CI pipeline
- `ai-governance-mcp-release.yml` — Automated release management for ai-governance server

## Related Resources

- **platform-service-template** — Scaffold and guidelines for new Core Services (Trinity Pattern)
- **AGENTS.md** — Universal governance policies for the dataforalltech platform
- **docs/architecture/trinity-pattern.md** — Architecture guidelines for MCP servers

## License

Proprietary — dataforalltech
