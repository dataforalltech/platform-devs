# MCP Discovery and Configuration

**Status:** ACTIVE  
**Last Updated:** 2026-05-09

---

## How MCPs are Discovered

MCPs are discovered through the **`.mcp.json` configuration file** centralized in `platform-service-template/.mcp.json`.

### Discovery Flow

```
Claude Code
    ↓
Reads ~/.claude/.mcp.json (or project .mcp.json)
    ↓
Loads all 18 MCP server entries with paths and commands
    ↓
Spawns each MCP server via stdio
    ↓
MCPs expose tools via SSE protocol
    ↓
Agent calls tools as: mcp__<service>__<tool>
```

---

## .mcp.json Structure

**Location:** `/home/dev/repos/platform-service-template/.mcp.json`

**Format:**
```json
{
  "mcpServers": {
    "<mcp-name>": {
      "command": "python3",
      "args": ["-m", "src.server.mcp_server"],
      "cwd": "/path/to/mcp/server/root"
    }
  }
}
```

**Example entry:**
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

## Complete MCP Catalog (18 Total)

### Infrastructure MCPs (12)

**Paths:** `/home/dev/repos/platform-devs/<name>-mcp-server/`

| Name | Package | Purpose | Key Tools |
|------|---------|---------|-----------|
| `session-mcp` | `session-mcp-server` | Session/checkpoint mgmt | `save_checkpoint`, `resume_session`, `list_tasks` |
| `test-mcp` | `test-mcp-server` | Test planning and execution | `create_test_plan`, `generate_scenarios`, `record_result` |
| `config-mcp` | `config-mcp-server` | Config and credentials | `get_env_config`, `set_credential`, `get_tenant_config` |
| `services-mcp` | `services-mcp-server` | Service registry | `register_service`, `check_health`, `list_services` |
| `deploy-mcp` | `deploy-mcp-server` | GitHub, ACR, CI/CD | `create_pr`, `trigger_workflow`, `acr_build` |
| `agent-twin-mcp` | `agent-twin-mcp-server` | Agent auth and context | `authenticate`, `whoami`, `get_twin_context` |
| `docs-mcp` | `docs-mcp-server` | Docs validation | `check_required_docs`, `audit_repo`, `lint_markdown` |
| `pipeline-mcp` | `pipeline-mcp-server` | Service pipeline gates | `promote_service`, `add_gate_result`, `get_pipeline` |
| `qa-mcp` | `qa-mcp-server` | QA: test, lint, security | `run_unit_tests`, `run_linter`, `run_security_scan` |
| `infra-mcp` | `infra-mcp-server` | Infra: Terraform, cost | `terraform_plan`, `cost_estimate_infracost`, `request_vm` |
| `ai-governance-mcp` | `ai-governance-mcp-server` | AI governance rules | `validate_agent_decision`, `create_adr`, `get_service_ownership` |
| `audit-mcp` | `audit-mcp-server` | Audit logging | (Tools TBD in Phase 5) |

### Service MCPs (6)

**Paths:** `/home/dev/repos/platform-devs/services/<name>-mcp-server/`

| Name | Service | Purpose | Key Tools |
|------|---------|---------|-----------|
| `auth-mcp` | platform-auth | OIDC, JWT, tokens | `oidc_setup_provider`, `oidc_get_config` |
| `admin-mcp` | platform-admin | Admin operations | (Tools TBD in Phase 5) |
| `governance-mcp` | platform-governance | Governance workflows | (Tools TBD in Phase 5) |
| `scheduler-mcp` | platform-scheduler | Job scheduling | (Tools TBD in Phase 5) |
| `connectors-mcp` | platform-connectors | External integrations | (Tools TBD in Phase 5) |
| `cache-mcp` | platform-cache | Cache management | (Tools TBD in Phase 5) |

---

## Tool Naming Convention

All tools follow the pattern:

```
mcp__<service>__<category>_<action>
```

**Breakdown:**
- `mcp__` — Fixed prefix (MCP tool marker)
- `<service>` — MCP server name (lowercase, dash-separated)
  - Examples: `session-mcp`, `deploy-mcp`, `auth-mcp`
- `<category>` — Functional category (optional, lowercase)
  - Examples: `oidc_`, `terraform_`, `coverage_`
- `<action>` — Action verb (lowercase, underscore-separated)
  - Examples: `setup_provider`, `plan`, `check`

**Examples:**
```
mcp__session-mcp__save_checkpoint
mcp__deploy-mcp__create_pr
mcp__auth-mcp__oidc_setup_provider
mcp__qa-mcp__run_unit_tests
mcp__infra-mcp__terraform_plan
```

---

## Using MCPs in Code

### Loading Tool Schemas

Before invoking an MCP tool, load its schema:

```python
# In Claude Code / agent code
from tool_search import ToolSearch

# Load multiple schemas at once
ToolSearch("select:mcp__deploy-mcp__create_pr,mcp__deploy-mcp__merge_pr")
```

### Calling Tools

Tools are invoked with full parameters as defined in their schema:

```python
# Example: Create a PR via deploy-mcp
result = await mcp__deploy-mcp__create_pr(
    repo="platform-auth",
    title="Add JWT refresh endpoint",
    head="feature/jwt-refresh",
    base="develop",
    body="Implements automatic token refresh..."
)
```

### Error Handling

MCPs return structured errors:

```json
{
  "error": "ERROR_CODE",
  "details": "Human-readable error message",
  "status": 400,
  "context": {}
}
```

Common patterns:
- `VALIDATION_ERROR` — Invalid input parameters
- `NOT_FOUND` — Resource doesn't exist
- `PERMISSION_DENIED` — Insufficient privileges
- `QUOTA_EXCEEDED` — Rate limit or quota reached
- `UNAVAILABLE` — Service down or unreachable

---

## MCP Health and Registration

### Registering MCPs for Monitoring

Use `services-mcp` to register MCPs as monitored services:

```python
mcp__services-mcp__register_service(
  name="session-mcp",
  port=7090,
  host="localhost",
  url="http://localhost:7090",
  type="process",
  environment="dev",
  health_path="/health"
)
```

### Health Checks

Check individual MCP health:

```python
mcp__services-mcp__check_health(name="session-mcp")
```

Check all MCPs:

```python
mcp__services-mcp__check_all_health()
```

Response:
```json
{
  "name": "session-mcp",
  "overall_status": "healthy",
  "last_check_at": "2026-05-09T14:23:45Z",
  "http_status": 200,
  "response_time_ms": 12
}
```

---

## Development and Contribution

### Adding Tools to an Existing MCP

1. Implement tool in `src/server/tools.py` or `src/server/handlers/<tool>.py`
2. Define schema in tool docstring (Pydantic model)
3. Register in server initialization
4. Add tests in `tests/test_tools.py`
5. Run full test suite: `pytest tests/ --cov=src`
6. Ensure 80%+ coverage

### Creating a New MCP

1. Copy structure from `platform-devs/session-mcp-server`
2. Update `pyproject.toml` with correct name and metadata
3. Implement tools in `src/server/`
4. Add tests in `tests/`
5. Register in `.mcp.json`
6. Add to `test-all-mcps.yml` matrix
7. Document in service catalog

---

## Troubleshooting

### MCP not appearing in Claude Code

1. Verify `.mcp.json` exists in correct location
2. Check server path exists: `cd /home/dev/repos/platform-devs/{name}-mcp-server`
3. Install dependencies: `pip install -e ".[dev]"`
4. Test launch: `python3 -m src.server.mcp_server`
5. Check for Python version errors (require >=3.10)

### Tool not found

1. Load schema first: `ToolSearch("select:mcp__service__tool")`
2. Verify tool name follows convention
3. Check MCP server logs for initialization errors
4. Ensure dependencies installed

### Tool execution fails

1. Check parameter validation in tool schema
2. Review MCP server logs: `stderr` output
3. Verify service/database dependencies available
4. Check error response structure

---

## Related Documents

- [MCP Consolidation Complete](./mcp-consolidation-complete.md)
- [Test Workflow](../.github/workflows/test-all-mcps.yml)
- [AGENTS.md § 54 — MCP Standards](../../platform-service-template/AGENTS.md#54-mcp-standards)
- [Phase 5 Tool Specifications](../../platform-service-template/docs/phase-5-mcp-tool-specifications.md)
