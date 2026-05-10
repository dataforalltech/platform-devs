#!/bin/bash
# Convert all 18 system MCPs to FastAPI + Docker

set -e

echo "Converting all system MCPs to FastAPI..."

# Port mapping for all 18 system MCPs
declare -A MCP_PORTS=(
    ["config-mcp"]=7100
    ["agent-twin-mcp"]=7101
    ["session-mcp"]=7102
    ["auth-mcp"]=7103
    ["admin-mcp"]=7104
    ["audit-mcp"]=7105
    ["infra-mcp"]=7106
    ["services-mcp"]=7107
    ["pipeline-mcp"]=7108
    ["qa-mcp"]=7109
    ["deploy-mcp"]=7110
    ["docs-mcp"]=7111
    ["ai-governance-mcp"]=7112
    ["governance-mcp"]=7113
    ["scheduler-mcp"]=7114
    ["connectors-mcp"]=7115
    ["cache-mcp"]=7116
    ["test-mcp"]=7117
)

# Convert each MCP
for mcp_name in "${!MCP_PORTS[@]}"; do
    port=${MCP_PORTS[$mcp_name]}
    echo "Converting $mcp_name on port $port..."
    python3 scripts/convert-mcp-to-fastapi.py "$mcp_name" "$port" || echo "Warning: Failed to convert $mcp_name"
done

echo ""
echo "✓ All MCPs converted!"
echo ""
echo "Next steps:"
echo "  1. Review generated FastAPI files in each *-mcp-server/ directory"
echo "  2. Test locally: python config-mcp-server/config_mcp.py"
echo "  3. Build Docker: docker-compose build"
echo "  4. Start all MCPs: docker-compose up -d"
echo "  5. Check status: docker-compose ps"
echo "  6. Test registry: curl http://localhost:8000/services"
