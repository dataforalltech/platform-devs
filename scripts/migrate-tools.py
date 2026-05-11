#!/usr/bin/env python3
"""
Migrate tools from original *-mcp.py to new *-mcp-server/*_mcp.py
Extracts the tools list and tool implementations
"""

import re
import json
from pathlib import Path

MCP_MAPPING = {
    "config-mcp": ("config_mcp.py", 7100),
    "agent-twin-mcp": ("agent_twin_mcp.py", 7101),
    "session-mcp": ("session_mcp.py", 7102),
    "auth-mcp": ("auth_mcp.py", 7103),
    "admin-mcp": ("admin_mcp.py", 7104),
    "audit-mcp": ("audit_mcp.py", 7105),
    "infra-mcp": ("infra_mcp.py", 7106),
    "services-mcp": ("services_mcp.py", 7107),
    "pipeline-mcp": ("pipeline_mcp.py", 7108),
    "qa-mcp": ("qa_mcp.py", 7109),
    "deploy-mcp": ("deploy_mcp.py", 7110),
    "docs-mcp": ("docs_mcp.py", 7111),
    "ai-governance-mcp": ("ai_governance_mcp.py", 7112),
    "governance-mcp": ("governance_mcp.py", 7113),
    "scheduler-mcp": ("scheduler_mcp.py", 7114),
    "connectors-mcp": ("connectors_mcp.py", 7115),
    "cache-mcp": ("cache_mcp.py", 7116),
    "test-mcp": ("test_mcp.py", 7117),
}

def extract_tools_from_original(mcp_name: str) -> str:
    """Extract self.tools definition from original MCP file"""
    original_file = Path(f"/home/dev/repos/platform-devs/{mcp_name}.py")

    if not original_file.exists():
        print(f"  ⚠️  Original {mcp_name}.py not found, skipping tools")
        return "[]"

    try:
        with open(original_file) as f:
            content = f.read()

        # Find self.tools = [...]
        # This is tricky because it could span multiple lines
        # Simple approach: find the pattern and extract
        match = re.search(r'self\.tools\s*=\s*(\[(?:[^\[\]]*|\[.*?\])*\])', content, re.DOTALL)

        if not match:
            print(f"  ⚠️  Could not find self.tools in {mcp_name}.py")
            return "[]"

        tools_str = match.group(1)

        # Try to validate it's valid Python by checking brackets
        open_brackets = tools_str.count('[')
        close_brackets = tools_str.count(']')
        open_braces = tools_str.count('{')
        close_braces = tools_str.count('}')

        if open_brackets != close_brackets or open_braces != close_braces:
            print(f"  ⚠️  Tools definition has mismatched brackets")
            return "[]"

        # Clean up the string (remove extra whitespace)
        tools_str = re.sub(r'\n\s*', ' ', tools_str)
        tools_str = re.sub(r'\s+', ' ', tools_str)

        return tools_str

    except Exception as e:
        print(f"  ⚠️  Error extracting tools: {e}")
        return "[]"

def update_fastapi_mcp(mcp_name: str, tools_str: str):
    """Update FastAPI MCP with tools from original"""
    fastapi_file_name, port = MCP_MAPPING[mcp_name]
    fastapi_file = Path(f"/home/dev/repos/platform-devs/{mcp_name}-server/{fastapi_file_name}")

    if not fastapi_file.exists():
        print(f"  ✗ {fastapi_file} not found")
        return False

    try:
        with open(fastapi_file) as f:
            content = f.read()

        # Replace self.tools = []
        new_content = re.sub(
            r'self\.tools = \[\]',
            f'self.tools = {tools_str}',
            content
        )

        if new_content == content:
            print(f"  ⚠️  No replacement made in {mcp_name}")
            return False

        with open(fastapi_file, 'w') as f:
            f.write(new_content)

        print(f"  ✓ Updated {mcp_name}")
        return True

    except Exception as e:
        print(f"  ✗ Error updating {mcp_name}: {e}")
        return False

if __name__ == "__main__":
    print("Migrating tools from original MCPs to FastAPI...\n")

    success = 0
    failed = 0

    for mcp_name in sorted(MCP_MAPPING.keys()):
        print(f"Processing {mcp_name}...")

        tools_str = extract_tools_from_original(mcp_name)

        if update_fastapi_mcp(mcp_name, tools_str):
            success += 1
        else:
            failed += 1

    print(f"\n✓ Success: {success}")
    print(f"✗ Failed/Partial: {failed}")
    print("\nNext: docker-compose build && docker-compose up -d")
