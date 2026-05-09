# MCP Startup Guide — platform-devs

## Problem

The `.mcp.json` configuration file in the template project is not automatically discovered by Claude Code. MCPs must be registered manually via `claude mcp add` command.

## Solution: Register MCPs Locally

Run these commands from the `platform-service-template` directory to register all 11 MCPs:

```bash
# Navigate to template
cd /home/dev/repos/platform-service-template

# Register each MCP (adjust paths as needed)
cd /home/dev/repos/platform-devs/session-mcp-server && \
  claude mcp add session-mcp -- python3 -m src.server.mcp_server

cd /home/dev/repos/platform-devs/test-mcp-server && \
  claude mcp add test-mcp -- python3 -m src.server.mcp_server

cd /home/dev/repos/platform-devs/config-mcp-server && \
  claude mcp add config-mcp -- python3 -m src.server.mcp_server

cd /home/dev/repos/platform-devs/agent-twin-mcp-server && \
  claude mcp add agent-twin-mcp -- python3 -m src.server.mcp_server

cd /home/dev/repos/platform-devs/deploy-mcp-server && \
  claude mcp add deploy-mcp -- python3 -m src.server.mcp_server

cd /home/dev/repos/platform-devs/services-mcp-server && \
  claude mcp add services-mcp -- python3 -m src.server.mcp_server

cd /home/dev/repos/platform-devs/docs-mcp-server && \
  claude mcp add docs-mcp -- python3 -m src.server.mcp_server

cd /home/dev/repos/platform-devs/qa-mcp-server && \
  claude mcp add qa-mcp -- python3 -m src.server.mcp_server

cd /home/dev/repos/platform-devs/pipeline-mcp-server && \
  claude mcp add pipeline-mcp -- python3 -m src.server.mcp_server

cd /home/dev/repos/platform-devs/infra-mcp-server && \
  claude mcp add infra-mcp -- python3 -m src.server.mcp_server

cd /home/dev/repos/platform-devs/ai-governance-mcp-server && \
  claude mcp add ai-governance-mcp -- python3 -m src.server.mcp_server
```

## Verify Registration

```bash
claude mcp list
```

You should see all 11 MCPs listed with status ✓ (connected).

## Alternative: Use .mcp.json (if supported in future Claude Code versions)

The `.mcp.json` file in `platform-service-template/` defines all servers. When a new Claude Code version fully supports `.mcp.json`, MCPs will be auto-discovered without manual registration.

## Architecture

Each MCP server follows the **Trinity Pattern**:
- **REST API** — Service endpoints (port 8001)
- **Library** — Python package (src/)
- **MCP Server** — AI agent interface (src/server/mcp_server.py)

All 11 servers are stateless stdio processes that wrap HTTP calls to their respective service APIs.

## Troubleshooting

**MCPs show "Failed to connect"**
- Verify the server directory exists and contains `src/server/mcp_server.py`
- Ensure Python 3.10+ is available
- Check if dependencies are installed: `pip install -e ".[dev]"`

**MCPs not appearing after registration**
- Clear local config: `rm ~/.claude.json`
- Re-run registration commands
- Verify `claude mcp list` shows the servers

**Authentication failures**
- Some MCPs require tokens (e.g., TWIN_TOKEN for agent-twin-mcp)
- Set env vars before starting Claude Code or via `claude mcp add -e KEY=value`
- See individual server README.md for auth requirements
