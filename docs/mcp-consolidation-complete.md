# MCP Consolidation Complete — 18 Unified Servers

**Status:** COMPLETE  
**Date:** 2026-05-09  
**Version:** 1.0

---

## Overview

All 18 MCP servers for the platform are now consolidated in the dedicated `platform-devs` repository with unified CI/CD, testing, and health checks.

**Total MCPs:** 18
- **Infrastructure MCPs:** 12 (root level)
- **Service MCPs:** 6 (in `services/`)

---

## Consolidated MCP Inventory

### Infrastructure MCPs (12)

Located in `/home/dev/repos/platform-devs/*-mcp-server/`

| MCP | Purpose | Port | Status |
|-----|---------|------|--------|
| `session-mcp` | Session management for Claude Code | 7090 | ✅ Active |
| `test-mcp` | Test execution and validation | 7091 | ✅ Active |
| `config-mcp` | Configuration and credential management | 7099 | ✅ Active |
| `services-mcp` | Service registry and health checks | 7100 | ✅ Active |
| `deploy-mcp` | GitHub API, ACR, deployments | 7101 | ✅ Active |
| `agent-twin-mcp` | Agent authentication and context | 7098 | ✅ Active |
| `docs-mcp` | Documentation scanning and validation | 7102 | ✅ Active |
| `pipeline-mcp` | Service pipeline and gates | 7103 | ✅ Active |
| `qa-mcp` | QA: testing, lint, security, accessibility | 7104 | ✅ Active |
| `infra-mcp` | Infrastructure: Terraform, cost, policy | 7105 | ✅ Active |
| `ai-governance-mcp` | AI governance rules and decisions | 7106 | ✅ Active |
| `audit-mcp` | Audit logging and compliance | 7107 | ✅ Active |

### Service MCPs (6)

Located in `/home/dev/repos/platform-devs/services/*-mcp-server/`

| MCP | Service | Purpose | Status |
|-----|---------|---------|--------|
| `auth-mcp` | platform-auth | JWT, OIDC, token management | ✅ Active |
| `admin-mcp` | platform-admin | Admin operations and dashboards | ✅ Active |
| `governance-mcp` | platform-governance | Governance rules and workflows | ✅ Active |
| `scheduler-mcp` | platform-scheduler | Job scheduling and orchestration | ✅ Active |
| `connectors-mcp` | platform-connectors | External integrations | ✅ Active |
| `cache-mcp` | platform-cache | Cache operations and management | ✅ Active |

---

## Central Configuration

### .mcp.json

Location: `/home/dev/repos/platform-service-template/.mcp.json`

Contains all 18 MCP server entries with:
- Command: `python3 -m src.server.mcp_server`
- CWD: Absolute path to each server directory
- Unified entry point for Claude Code

**Entry example:**
```json
{
  "session-mcp": {
    "command": "python3",
    "args": ["-m", "src.server.mcp_server"],
    "cwd": "/home/dev/repos/platform-devs/session-mcp-server"
  }
}
```

---

## CI/CD Unification

### Workflow: test-all-mcps.yml

Location: `/home/dev/repos/platform-devs/.github/workflows/test-all-mcps.yml`

**Features:**
- Parallel testing of all 18 MCPs (6 concurrent jobs max)
- For each MCP:
  - Dependency installation (`pip install -e ".[dev]"`)
  - Linting (ruff check + format)
  - Type checking (mypy)
  - Unit tests with pytest
  - Coverage validation (minimum 80%)
- Artifact collection: coverage.json per MCP
- Summary report in GitHub Actions

**Matrix jobs:**
- `test-infrastructure-mcps`: 12 MCPs in parallel
- `test-service-mcps`: 6 MCPs in parallel
- `coverage-summary`: Aggregates results

**Triggers:** push to `develop`, `main`, `master` and pull requests

---

## Quality Criteria

All MCPs must meet:
1. **Test Coverage:** >= 80% (enforced in workflow)
2. **Linting:** ruff check + format pass
3. **Type Safety:** mypy with Python 3.12+
4. **Dependencies:** Listed in `pyproject.toml` with dev extras

---

## Health Checks

### services-mcp integration

Services-mcp can register and monitor all MCPs via health endpoints:

```bash
# Register an MCP as a service
mcp__services-mcp__register_service(
  name="session-mcp",
  port=7090,
  host="localhost",
  url="http://localhost:7090",
  type="process",
  environment="dev",
  health_path="/health"
)

# Check health
mcp__services-mcp__check_health(name="session-mcp")

# Check all
mcp__services-mcp__check_all_health()
```

---

## Discovery and Documentation

### MCP Discovery

Agents can discover MCPs via:
1. **Direct reference:** `mcp__<service>__<tool>`
2. **Schema loading:** ToolSearch API
3. **Central registry:** `.mcp.json`

### Tool Naming Convention

All tools follow the pattern:
```
mcp__<service>__<category>_<action>
```

Example:
- `mcp__session-mcp__save_checkpoint`
- `mcp__deploy-mcp__create_pr`
- `mcp__auth-mcp__oidc_setup_provider`

---

## Maintenance and Updates

### Adding a New MCP

1. Create server in `platform-devs/[services/]{name}-mcp-server/`
2. Add entry to `.mcp.json`
3. Update `test-all-mcps.yml` matrix
4. Ensure 80% test coverage
5. Document in service catalog

### Updating MCPs

**Infrastructure MCPs:** Update in root directory, commit to platform-devs
**Service MCPs:** Update in `services/` subdirectory, may be auto-synced from source services

---

## Timeline

| Date | Milestone |
|------|-----------|
| 2026-05-05 | Phase 4c: Implement platform-integrations MCP |
| 2026-05-09 | Phase 5: Consolidation complete — all 18 MCPs unified |
| 2026-05-09 | CI/CD workflow activated: test-all-mcps.yml |
| 2026-05-09 | Documentation and discovery complete |

---

## Related Documents

- [platform-devs/README.md](../README.md) — Repository overview
- [platform-service-template/.mcp.json](../../platform-service-template/.mcp.json) — Central config
- [AGENTS.md § 54 — MCP Standards](../../platform-service-template/AGENTS.md#54-mcp-standards) — Tool naming and governance
- [Phase 5 MCP Tool Specifications](../../platform-service-template/docs/phase-5-mcp-tool-specifications.md) — Tool definitions

---

## Next Steps

1. ✅ All 18 MCPs consolidated
2. ✅ Central `.mcp.json` created
3. ✅ CI/CD workflow activated
4. ⚠️ Run first test suite (validate 80% coverage on all MCPs)
5. ⚠️ Register MCPs in services-mcp registry
6. ⚠️ Monitor health checks in production
