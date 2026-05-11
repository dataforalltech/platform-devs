#!/bin/bash
# setup-mcps.sh - MCP Quick Setup for Teams

set -e

echo ""
echo "╔════════════════════════════════════════════════╗"
echo "║   MCP Setup - Shared HTTP Services             ║"
echo "║   platform-devs                                ║"
echo "╚════════════════════════════════════════════════╝"
echo ""

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Step 1: Check prerequisites
echo "📋 Step 1: Checking prerequisites..."
echo ""

# Check if in repo directory
if [ ! -f "docker-compose-system.yml" ]; then
    echo -e "${RED}✗${NC} Not in platform-devs directory"
    echo "Run from: /path/to/platform-devs/"
    exit 1
fi
echo -e "${GREEN}✓${NC} Found platform-devs repository"

# Check Python
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}✗${NC} Python3 not found"
    echo "Install from: https://www.python.org/downloads/"
    exit 1
fi
PYTHON_VERSION=$(python3 --version | awk '{print $2}')
echo -e "${GREEN}✓${NC} Found Python ${PYTHON_VERSION}"

# Check curl
if ! command -v curl &> /dev/null; then
    echo -e "${YELLOW}⚠${NC} curl not found (optional)"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Step 2: Create wrapper directory
echo "📂 Step 2: Creating MCP wrapper directory..."
echo ""

if [ "$OS" = "Windows_NT" ]; then
    WRAPPER_DIR="$USERPROFILE/mcp-wrapper"
else
    WRAPPER_DIR="$HOME/mcp-wrapper"
fi

mkdir -p "$WRAPPER_DIR"
echo -e "${GREEN}✓${NC} Created: $WRAPPER_DIR"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Step 3: Copy wrapper
echo "📋 Step 3: Copying wrapper script..."
echo ""

if [ ! -f "mcp-http-wrapper.py" ]; then
    echo -e "${RED}✗${NC} mcp-http-wrapper.py not found in current directory"
    exit 1
fi

cp mcp-http-wrapper.py "$WRAPPER_DIR/"
echo -e "${GREEN}✓${NC} Copied: $WRAPPER_DIR/mcp-http-wrapper.py"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Step 4: Install dependencies
echo "📦 Step 4: Installing dependencies..."
echo ""

echo "Running: pip install httpx"
python3 -m pip install -q httpx 2>/dev/null || {
    echo -e "${YELLOW}⚠${NC} Failed to install httpx automatically"
    echo "Manual: python3 -m pip install httpx"
}
echo -e "${GREEN}✓${NC} Dependencies ready"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Step 5: Create or update settings.json
echo "⚙️ Step 5: Updating Claude Code settings..."
echo ""

# Determine settings file path
if [ "$OS" = "Windows_NT" ]; then
    SETTINGS_FILE="$APPDATA/Claude/settings.json"
else
    SETTINGS_FILE="$HOME/.claude/settings.json"
fi

SETTINGS_DIR=$(dirname "$SETTINGS_FILE")
mkdir -p "$SETTINGS_DIR"

# Create settings JSON
python3 << 'PYTHON_EOF'
import json
import os
from pathlib import Path

settings_file = Path(os.environ['SETTINGS_FILE'])
wrapper_dir = os.environ['WRAPPER_DIR']

# Load or create settings
if settings_file.exists():
    with open(settings_file, 'r') as f:
        settings = json.load(f)
else:
    settings = {"mcpServers": {}, "preferences": {}}

# Ensure mcpServers exists
if "mcpServers" not in settings:
    settings["mcpServers"] = {}

# Add wrapper
settings["mcpServers"]["mcp-http-wrapper"] = {
    "command": "python3",
    "args": [str(Path(wrapper_dir) / "mcp-http-wrapper.py")],
    "disabled": False,
    "alwaysAllow": ["mcp__mcp_http_wrapper__*"]
}

# Save
with open(settings_file, 'w') as f:
    json.dump(settings, f, indent=2)

print(f"✓ Settings updated: {settings_file}")
PYTHON_EOF

export SETTINGS_FILE="$SETTINGS_FILE"
export WRAPPER_DIR="$WRAPPER_DIR"

python3 << PYTHON_EOF
import json
import os
from pathlib import Path

settings_file = Path("$SETTINGS_FILE")
wrapper_dir = "$WRAPPER_DIR"

if settings_file.exists():
    with open(settings_file, 'r') as f:
        settings = json.load(f)
else:
    settings = {"mcpServers": {}, "preferences": {}}

if "mcpServers" not in settings:
    settings["mcpServers"] = {}

settings["mcpServers"]["mcp-http-wrapper"] = {
    "command": "python3",
    "args": [str(Path(wrapper_dir) / "mcp-http-wrapper.py")],
    "disabled": False,
    "alwaysAllow": ["mcp__mcp_http_wrapper__*"]
}

with open(settings_file, 'w') as f:
    json.dump(settings, f, indent=2)

print(f"✓ Settings updated: {settings_file}")
PYTHON_EOF

echo -e "${GREEN}✓${NC} Settings: $SETTINGS_FILE"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Step 6: Test connection
echo "🔗 Step 6: Testing connection to claude-dev..."
echo ""

if command -v curl &> /dev/null; then
    if curl -s http://claude-dev:8000/services > /dev/null 2>&1; then
        echo -e "${GREEN}✓${NC} Connected to claude-dev:8000"
        MCP_COUNT=$(curl -s http://claude-dev:8000/services | python3 -c "import sys, json; print(len(json.load(sys.stdin)))" 2>/dev/null || echo "?")
        echo -e "${GREEN}✓${NC} Found ${MCP_COUNT} MCPs"
    else
        echo -e "${YELLOW}⚠${NC} Could not connect to claude-dev:8000"
        echo "   Make sure MCPs are running:"
        echo "   docker compose -f docker-compose-system.yml up -d"
    fi
else
    echo -e "${YELLOW}⚠${NC} curl not available, skipping connection test"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Final instructions
echo "✅ Setup Complete!"
echo ""
echo "📋 Next Steps:"
echo ""
echo "1. CLOSE Claude Code Desktop completely"
echo "   • Windows: Task Manager → End task"
echo "   • Mac: Cmd+Q"
echo "   • Linux: pkill claude or killall claude"
echo ""
echo "2. REOPEN Claude Code Desktop"
echo ""
echo "3. VERIFY in Settings → MCP Servers"
echo "   • You should see: mcp-http-wrapper (Connected)"
echo ""
echo "4. TEST in a new chat"
echo "   • Ask: 'What tools are available?'"
echo "   • Should show ~170+ tools from MCPs"
echo ""
echo "📁 Installation paths:"
echo "   Wrapper: $WRAPPER_DIR/mcp-http-wrapper.py"
echo "   Settings: $SETTINGS_FILE"
echo ""
echo "📖 Documentation:"
echo "   • MCP_SERVICES_README.md - Quick start"
echo "   • MCP_WRAPPER_SETUP.md - Detailed guide"
echo "   • MCP_SHARE_GUIDE.md - Team sharing"
echo ""
echo "🆘 If you need help:"
echo "   • Check logs: tail -f /tmp/mcp-wrapper.log"
echo "   • Test MCPs: curl http://claude-dev:8000/services"
echo "   • Read: MCP_SHARE_GUIDE.md (Troubleshooting section)"
echo ""
