# MCP Server Registration Guide

## Overview

MCP (Model Context Protocol) servers must be registered at the **home-level** Claude Code configuration to be discoverable and usable via the `/mcp` command.

## Registration Location

**Primary Registration: `/home/dev/.claude.json`**

All MCP servers are registered in the global `mcpServers` section of `/home/dev/.claude.json`. This is the canonical location where Claude Code discovers available MCP servers.

## Registration Format

Add a new entry to the `mcpServers` object in `/home/dev/.claude.json`:

```json
{
  "mcpServers": {
    "your-mcp-name": {
      "command": "bash",
      "args": [
        "-c",
        "cd /path/to/your/mcp-server && your-startup-command"
      ]
    }
  }
}
```

### Examples

**Python MCP** (using module pattern):
```json
"session-mcp": {
  "command": "bash",
  "args": [
    "-c",
    "cd /home/dev/repos/platform-devs/session-mcp-server && python3 -m src.server.mcp_server"
  ]
}
```

**Node.js MCP** (using compiled output):
```json
"frontzilla-pixelfera-mcp-server": {
  "command": "bash",
  "args": [
    "-c",
    "cd /home/dev/repos/platform-devs/frontzilla-pixelfera-mcp-server && node dist/server.js"
  ]
}
```

**With Environment Variables:**
```json
"config-mcp": {
  "command": "bash",
  "args": [
    "-c",
    "cd /home/dev/repos/platform-devs/config-mcp-server && python3 -m src.server.mcp_server"
  ],
  "env": {
    "MCP_SERVICE_BASE_URL": "http://localhost:8001",
    "CONFIG_MCP_TOKEN": "demo-token"
  }
}
```

Or with `cwd` and `env` (alternative format):
```json
"config-mcp": {
  "command": "python3",
  "args": ["-m", "src.server.mcp_server"],
  "cwd": "/home/dev/repos/platform-devs/config-mcp-server",
  "env": {
    "MCP_SERVICE_BASE_URL": "http://localhost:8001"
  }
}
```

## Key Requirements

1. **Server Name** — The key should match the MCP server's name (e.g., `"session-mcp"`, `"deploy-mcp"`)
2. **Command** — The executable: `bash`, `python3`, `node`, etc.
3. **Args** — Command arguments; for bash, use `-c "cd ... && command"` pattern
4. **Working Directory** — Either in the bash command (`cd /path && cmd`) or via `cwd` parameter
5. **Startup Command** — The actual server startup (e.g., `python3 -m src.server.mcp_server` or `node dist/server.js`)

## Optional: Project-Level Configuration

**Secondary Registration: `/home/dev/repos/platform-devs/.claude/.mcp.json`**

Project-level `.mcp.json` files can be created for convenience or documentation purposes, but they do NOT make MCPs discoverable in Claude Code. The home-level `/home/dev/.claude.json` is the single source of truth.

Example project-level structure (informational only):
```json
{
  "mcpServers": {
    "frontzilla-pixelfera-mcp-server": {
      "command": "node",
      "args": ["dist/server.js"],
      "cwd": "/home/dev/repos/platform-devs/frontzilla-pixelfera-mcp-server"
    }
  }
}
```

## Verification

After adding an MCP server to `/home/dev/.claude.json`:

1. Run `/mcp` in Claude Code
2. The MCP should appear in the available servers list
3. Tools from that MCP are now available for use

## Server Startup Requirements

- **stdio-based**: The MCP server must communicate via stdin/stdout (standard for MCP SDK)
- **Build requirement**: For compiled languages (TypeScript, etc.), the `args` command should point to built output
  - Example: `node dist/server.js` (not `ts-node src/server.ts`)
- **Initialization**: The server starts when a client connects and should respond to the MCP protocol

## Checklist for New MCP Servers

- [ ] Server is built/compiled (if needed)
- [ ] Server implements MCP protocol via stdio transport
- [ ] Entry added to `mcpServers` in `/home/dev/.claude.json`
- [ ] Server name matches package name or canonical identifier
- [ ] Startup command tested locally
- [ ] Verified via `/mcp` command in Claude Code
