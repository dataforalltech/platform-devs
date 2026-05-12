"""ArchZilla MCP Server — Software Architecture Specialist."""
from __future__ import annotations

import os

import asyncio
from src.prompts.system_prompt import SYSTEM_PROMPT
from src.tools.archzilla_tools import (
    generate_solution_blueprint,
    generate_c4_diagram,
    generate_architecture,
    stub_tool,
)
from shared.hybrid_server import HybridMCPServer

_TOOLS = {
    "generate_solution_blueprint": {
        "description": "Gera blueprint de arquitetura completo",
        "schema": {
            "type": "object",
            "properties": {"architecture_name": {"type": "string"}},
        },
    },
    "generate_c4_diagram": {
        "description": "Gera diagrama C4 de arquitetura",
        "schema": {
            "type": "object",
            "properties": {
                "system": {"type": "string"},
                "level": {"type": "integer"},
            },
        },
    },
    "generate_architecture": {
        "description": "Gera design de arquitetura",
        "schema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
        },
    },
    "status": {"description": "Status check", "schema": {"type": "object"}},
}

_DISPATCH = {
    "generate_solution_blueprint": lambda a: generate_solution_blueprint(
        architecture_name=a.get("architecture_name", "System")
    ),
    "generate_c4_diagram": lambda a: generate_c4_diagram(
        system=a.get("system", "System"),
        level=a.get("level", 1),
    ),
    "generate_architecture": lambda a: generate_architecture(name=a.get("name", "Architecture")),
    "status": lambda a: stub_tool(),
}

def main() -> None:
    server = HybridMCPServer("archzilla-mcp-server", _TOOLS, _DISPATCH, SYSTEM_PROMPT)
    asyncio.run(server.run(http_port=int(os.getenv("MCP_PORT", "7100"))))

if __name__ == "__main__":
    main()
