#!/usr/bin/env python3
"""
Install MCP HTTP Wrapper for Claude Code Desktop
Automaticamente configura tudo para usar MCPs remotos
"""

import os
import json
import shutil
import subprocess
import sys
from pathlib import Path

def print_header(text):
    print(f"\n{'='*60}")
    print(f"  {text}")
    print(f"{'='*60}\n")

def print_success(text):
    print(f"✅ {text}")

def print_error(text):
    print(f"❌ {text}")

def print_warning(text):
    print(f"⚠️  {text}")

def print_info(text):
    print(f"ℹ️  {text}")

# Step 1: Determine OS and paths
print_header("Step 1: Detecting System")

if sys.platform == "win32":
    HOME = Path.home()
    WRAPPER_DIR = HOME / "mcp-wrapper"
    SETTINGS_PATH = HOME / "AppData" / "Local" / "Claude" / "settings.json"
    PYTHON_CMD = "python"
    print_info(f"Detected Windows")
    print_info(f"Home: {HOME}")
else:
    HOME = Path.home()
    WRAPPER_DIR = HOME / "mcp-wrapper"
    SETTINGS_PATH = HOME / ".claude" / "settings.json"
    PYTHON_CMD = "python3"
    print_info(f"Detected {sys.platform}")
    print_info(f"Home: {HOME}")

print_success(f"Wrapper directory: {WRAPPER_DIR}")
print_success(f"Settings file: {SETTINGS_PATH}")

# Step 2: Create wrapper directory
print_header("Step 2: Creating wrapper directory")

try:
    WRAPPER_DIR.mkdir(parents=True, exist_ok=True)
    print_success(f"Created {WRAPPER_DIR}")
except Exception as e:
    print_error(f"Failed to create directory: {e}")
    sys.exit(1)

# Step 3: Copy wrapper script
print_header("Step 3: Copying MCP wrapper script")

# Try to find the source file
source_paths = [
    Path(__file__).parent / "mcp-http-wrapper.py",
    Path("/home/dev/mcp-http-wrapper.py"),
    Path("./mcp-http-wrapper.py"),
]

source_file = None
for path in source_paths:
    if path.exists():
        source_file = path
        break

if not source_file:
    print_error("Could not find mcp-http-wrapper.py")
    print_warning("Please copy mcp-http-wrapper.py manually to the following location:")
    print_warning(f"  {WRAPPER_DIR / 'mcp-http-wrapper.py'}")
    print_info("Then run this script again.")
    sys.exit(1)

try:
    dest_file = WRAPPER_DIR / "mcp-http-wrapper.py"
    shutil.copy2(source_file, dest_file)
    print_success(f"Copied wrapper to {dest_file}")
except Exception as e:
    print_error(f"Failed to copy wrapper: {e}")
    sys.exit(1)

# Step 4: Install dependencies
print_header("Step 4: Installing Python dependencies")

try:
    print_info("Installing httpx...")
    subprocess.check_call([PYTHON_CMD, "-m", "pip", "install", "-q", "httpx"])
    print_success("Installed httpx")
except Exception as e:
    print_warning(f"Failed to install httpx: {e}")
    print_warning("You may need to run manually:")
    print_warning(f"  {PYTHON_CMD} -m pip install httpx")

# Step 5: Update settings.json
print_header("Step 5: Updating Claude Code settings")

# Ensure settings directory exists
SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)

# Load or create settings
if SETTINGS_PATH.exists():
    try:
        with open(SETTINGS_PATH, 'r') as f:
            settings = json.load(f)
        print_info("Loaded existing settings.json")
    except Exception as e:
        print_error(f"Failed to load settings: {e}")
        settings = {"mcpServers": {}, "preferences": {}}
else:
    print_info("Creating new settings.json")
    settings = {"mcpServers": {}, "preferences": {}}

# Add MCP server config
if "mcpServers" not in settings:
    settings["mcpServers"] = {}

settings["mcpServers"]["mcp-http-wrapper"] = {
    "command": PYTHON_CMD,
    "args": [str(WRAPPER_DIR / "mcp-http-wrapper.py")],
    "disabled": False,
    "alwaysAllow": ["mcp__mcp_http_wrapper__*"]
}

# Save settings
try:
    with open(SETTINGS_PATH, 'w') as f:
        json.dump(settings, f, indent=2)
    print_success(f"Updated settings.json")
except Exception as e:
    print_error(f"Failed to update settings: {e}")
    print_warning("Manual fix needed: Add the following to your settings.json:")
    print_warning(json.dumps(settings["mcpServers"]["mcp-http-wrapper"], indent=2))
    sys.exit(1)

# Step 6: Verify installation
print_header("Step 6: Verifying installation")

wrapper_file = WRAPPER_DIR / "mcp-http-wrapper.py"
if wrapper_file.exists():
    print_success(f"✓ Wrapper file exists: {wrapper_file}")
else:
    print_error(f"✗ Wrapper file not found: {wrapper_file}")

if SETTINGS_PATH.exists():
    print_success(f"✓ Settings file updated: {SETTINGS_PATH}")
else:
    print_error(f"✗ Settings file not found: {SETTINGS_PATH}")

# Test connection
print_header("Step 7: Testing connection to claude-dev")

try:
    import httpx
    response = httpx.get("http://claude-dev:8000/services", timeout=5)
    if response.status_code == 200:
        services = response.json()
        count = len(services) if isinstance(services, list) else len(services.get("services", []))
        print_success(f"✓ Connected to claude-dev")
        print_success(f"✓ Found {count} MCPs")
    else:
        print_warning(f"Unexpected status: {response.status_code}")
        print_warning("MCPs might not be running yet")
except Exception as e:
    print_warning(f"Could not connect to claude-dev:8000")
    print_warning(f"Error: {e}")
    print_info("Make sure MCPs are running on claude-dev:")
    print_info("  docker compose -f docker-compose-system.yml up -d")

# Final instructions
print_header("✅ Installation Complete!")

print("\n📋 Next Steps:\n")
print("1. CLOSE Claude Code Desktop completely")
print("   (Windows: Task Manager → End task 'Claude')")
print("   (Mac: Cmd+Q)")
print("   (Linux: killall claude or pkill claude)\n")

print("2. REOPEN Claude Code Desktop\n")

print("3. VERIFY installation:")
print("   - Go to Settings → MCP Servers")
print("   - You should see 'mcp-http-wrapper' listed")
print("   - Status should show 'Connected'\n")

print("4. TEST it works:")
print("   - Open a new chat")
print("   - Ask: 'What tools are available?'")
print("   - You should see ~170 tools from the MCPs\n")

print("📁 Installation paths:")
print(f"   Wrapper: {WRAPPER_DIR / 'mcp-http-wrapper.py'}")
print(f"   Settings: {SETTINGS_PATH}")
print(f"   Logs: /tmp/mcp-wrapper.log (Linux/Mac) or C:\\Users\\{os.getenv('USERNAME')}\\AppData\\Local\\Temp\\mcp-wrapper.log (Windows)\n")

print("🆘 Troubleshooting:")
print("   If tools don't appear:")
print("   - Check logs: tail -f /tmp/mcp-wrapper.log")
print("   - Verify MCPs are running: curl http://claude-dev:8000/services")
print("   - Restart Claude Code Desktop\n")

print("✨ Done!")
