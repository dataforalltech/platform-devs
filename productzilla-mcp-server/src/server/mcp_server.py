"""ProductZilla MCP Server — Product Strategy Specialist."""
from __future__ import annotations

import os

import asyncio
from src.prompts.system_prompt import SYSTEM_PROMPT
from src.tools.productzilla_tools import (
    generate_feature_spec,
    generate_go_to_market_brief,
    define_product_vision,
    generate_release_plan,
    stub_tool,
)
from shared.hybrid_server import HybridMCPServer

_TOOLS = {
    "generate_feature_spec": {
        "description": "Gera especificação completa de feature",
        "schema": {
            "type": "object",
            "properties": {
                "feature": {"type": "string"},
                "objective": {"type": "string"},
            },
        },
    },
    "generate_go_to_market_brief": {
        "description": "Gera brief de GTM para lançamento",
        "schema": {"type": "object"},
    },
    "define_product_vision": {
        "description": "Define visão, missão e metas do produto",
        "schema": {"type": "object"},
    },
    "generate_release_plan": {
        "description": "Gera plano de release do produto",
        "schema": {"type": "object"},
    },
    "status": {"description": "Status check", "schema": {"type": "object"}},
}

_DISPATCH = {
    "generate_feature_spec": lambda a: generate_feature_spec(
        feature=a.get("feature", "Feature"),
        objective=a.get("objective", ""),
    ),
    "generate_go_to_market_brief": lambda a: generate_go_to_market_brief(),
    "define_product_vision": lambda a: define_product_vision(),
    "generate_release_plan": lambda a: generate_release_plan(),
    "status": lambda a: stub_tool(),
}

def main() -> None:
    server = HybridMCPServer("productzilla-mcp-server", _TOOLS, _DISPATCH, SYSTEM_PROMPT)
    asyncio.run(server.run(http_port=int(os.getenv("MCP_PORT", "7100"))))

if __name__ == "__main__":
    main()
