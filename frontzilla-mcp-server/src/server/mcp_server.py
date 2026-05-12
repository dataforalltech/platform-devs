"""FrontZilla MCP Server — Frontend & UI Specialist."""
from __future__ import annotations

import os

import asyncio
from src.prompts.system_prompt import SYSTEM_PROMPT
from src.tools.frontzilla_tools import (
    generate_react_component,
    generate_nextjs_page,
    generate_storybook_story,
    generate_form_with_validation,
    stub_tool,
)
from shared.hybrid_server import HybridMCPServer

_TOOLS = {
    "generate_react_component": {
        "description": "Gera scaffold de componente React",
        "schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "variant": {"type": "string"},
            },
        },
    },
    "generate_nextjs_page": {
        "description": "Gera página Next.js 14+ com App Router",
        "schema": {
            "type": "object",
            "properties": {"route": {"type": "string"}},
        },
    },
    "generate_storybook_story": {
        "description": "Gera Storybook story (CSF 3.0)",
        "schema": {
            "type": "object",
            "properties": {"component_name": {"type": "string"}},
        },
    },
    "generate_form_with_validation": {
        "description": "Gera formulário com React Hook Form + Zod",
        "schema": {
            "type": "object",
            "properties": {"form_name": {"type": "string"}},
        },
    },
    "status": {"description": "Status check", "schema": {"type": "object"}},
}

_DISPATCH = {
    "generate_react_component": lambda a: generate_react_component(
        name=a.get("name", "Component"),
        variant=a.get("variant", "functional"),
    ),
    "generate_nextjs_page": lambda a: generate_nextjs_page(route=a.get("route", "/")),
    "generate_storybook_story": lambda a: generate_storybook_story(
        component_name=a.get("component_name", "Component")
    ),
    "generate_form_with_validation": lambda a: generate_form_with_validation(
        form_name=a.get("form_name", "Form")
    ),
    "status": lambda a: stub_tool(),
}

def main() -> None:
    server = HybridMCPServer("frontzilla-mcp-server", _TOOLS, _DISPATCH, SYSTEM_PROMPT)
    asyncio.run(server.run(http_port=int(os.getenv("MCP_PORT", "7100"))))

if __name__ == "__main__":
    main()
