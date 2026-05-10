"""MCP server implementation for platform-governance."""

import asyncio
import json
import logging
from typing import Any

from mcp.server import Server
from mcp.types import TextContent, Tool

from ..config.settings import Settings
from ..tools import governance_tools

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

settings = Settings()
server = Server("governance-mcp")


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List all available tools."""
    return [
        Tool(
            name="governance_health_check",
            description="Check if platform-governance service is healthy",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
        Tool(
            name="governance_get_policy",
            description="Get a specific policy by ID",
            inputSchema={
                "type": "object",
                "properties": {
                    "policy_id": {
                        "type": "string",
                        "description": "The policy ID to retrieve",
                    }
                },
                "required": ["policy_id"],
            },
        ),
        Tool(
            name="governance_list_policies",
            description="List all available policies",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
        Tool(
            name="governance_check_access",
            description="Check if a user has access to perform an action on a resource",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "string",
                        "description": "The user ID to check",
                    },
                    "resource": {
                        "type": "string",
                        "description": "The resource being accessed",
                    },
                    "action": {
                        "type": "string",
                        "description": "The action being performed",
                    },
                },
                "required": ["user_id", "resource", "action"],
            },
        ),
        Tool(
            name="governance_list_permissions",
            description="List all available permissions",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
        Tool(
            name="governance_get_user_permissions",
            description="Get all permissions for a specific user",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "string",
                        "description": "The user ID to get permissions for",
                    }
                },
                "required": ["user_id"],
            },
        ),
        Tool(
            name="governance_update_rls",
            description="Update row-level security rules for a resource",
            inputSchema={
                "type": "object",
                "properties": {
                    "resource": {
                        "type": "string",
                        "description": "The resource name",
                    },
                    "rules": {
                        "type": "object",
                        "description": "Dictionary containing the RLS rules",
                    },
                },
                "required": ["resource", "rules"],
            },
        ),
        Tool(
            name="governance_get_rls",
            description="Get row-level security rules for a resource",
            inputSchema={
                "type": "object",
                "properties": {
                    "resource": {
                        "type": "string",
                        "description": "The resource name to get RLS rules for",
                    }
                },
                "required": ["resource"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Call a tool by name with the given arguments."""
    try:
        logger.info(f"Calling tool: {name}")

        if name == "governance_health_check":
            return await governance_tools.governance_health_check()
        elif name == "governance_get_policy":
            return await governance_tools.governance_get_policy(**arguments)
        elif name == "governance_list_policies":
            return await governance_tools.governance_list_policies()
        elif name == "governance_check_access":
            return await governance_tools.governance_check_access(**arguments)
        elif name == "governance_list_permissions":
            return await governance_tools.governance_list_permissions()
        elif name == "governance_get_user_permissions":
            return await governance_tools.governance_get_user_permissions(**arguments)
        elif name == "governance_update_rls":
            return await governance_tools.governance_update_rls(**arguments)
        elif name == "governance_get_rls":
            return await governance_tools.governance_get_rls(**arguments)
        else:
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "error": "ToolNotFound",
                            "details": f"Tool '{name}' not found",
                        }
                    ),
                )
            ]
    except Exception as e:
        logger.exception(f"Error calling tool {name}")
        return [
            TextContent(
                type="text",
                text=json.dumps(
                    {
                        "error": "InternalError",
                        "details": str(e),
                    }
                ),
            )
        ]


async def _run_server() -> None:
    """Run the MCP server over stdio."""
    from mcp import stdio_server

    async with stdio_server() as (read_stream, write_stream):
        logger.info("Starting governance-mcp server")
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def main() -> None:
    """Entry point for the MCP server."""
    logger.setLevel(getattr(logging, settings.log_level.upper()))
    asyncio.run(_run_server())


if __name__ == "__main__":
    main()
