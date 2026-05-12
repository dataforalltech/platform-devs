"""ProductZilla MCP Server — Product Strategy Specialist."""
from __future__ import annotations

import os

import asyncio
from src.prompts.system_prompt import SYSTEM_PROMPT
from src.tools.productzilla_tools import stub_tool
from shared.hybrid_server import HybridMCPServer

_TOOLS = {
    "status": {"description": "Status check", "schema": {"type": "object"}},
}

_DISPATCH = {
    "status": lambda a: stub_tool(),
}

def main() -> None:
    server = HybridMCPServer("productzilla-mcp-server", _TOOLS, _DISPATCH, SYSTEM_PROMPT)
    asyncio.run(server.run(http_port=int(os.getenv("MCP_PORT", "7100"))))

if __name__ == "__main__":
    main()
