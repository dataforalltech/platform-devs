"""MCP server implementation for platform-admin."""

import asyncio
import json
import logging
from typing import Any

from mcp.server import Server
from mcp.types import TextContent, Tool

from ..config.settings import Settings
from ..tools import admin_tools

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

settings = Settings()
server = Server("admin-mcp")


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List all available tools."""
    return [
        Tool(
            name="admin_health_check",
            description="Check if platform-admin service is healthy",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
        Tool(
            name="admin_list_users",
            description="List all users in the system",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
        Tool(
            name="admin_get_user",
            description="Get details of a specific user",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "string",
                        "description": "The user ID",
                    }
                },
                "required": ["user_id"],
            },
        ),
        Tool(
            name="admin_create_user",
            description="Create a new user",
            inputSchema={
                "type": "object",
                "properties": {
                    "email": {
                        "type": "string",
                        "description": "User email address",
                    },
                    "name": {
                        "type": "string",
                        "description": "User full name",
                    },
                    "domain_id": {
                        "type": "string",
                        "description": "Optional domain ID",
                    },
                },
                "required": ["email", "name"],
            },
        ),
        Tool(
            name="admin_list_domains",
            description="List all domains in the system",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
        Tool(
            name="admin_list_tenants",
            description="List all tenants in the system",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
        Tool(
            name="admin_get_tenant",
            description="Get details of a specific tenant",
            inputSchema={
                "type": "object",
                "properties": {
                    "tenant_id": {
                        "type": "string",
                        "description": "The tenant ID",
                    }
                },
                "required": ["tenant_id"],
            },
        ),
        Tool(
            name="admin_assign_role",
            description="Assign a role to a user",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "string",
                        "description": "The user ID",
                    },
                    "role_id": {
                        "type": "string",
                        "description": "The role ID to assign",
                    },
                },
                "required": ["user_id", "role_id"],
            },
        ),
        Tool(
            name="admin_list_roles",
            description="List all available roles",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Call a tool by name with the given arguments."""
    try:
        logger.info(f"Calling tool: {name}")

        if name == "admin_health_check":
            return await admin_tools.admin_health_check()
        elif name == "admin_list_users":
            return await admin_tools.admin_list_users()
        elif name == "admin_get_user":
            return await admin_tools.admin_get_user(**arguments)
        elif name == "admin_create_user":
            return await admin_tools.admin_create_user(**arguments)
        elif name == "admin_list_domains":
            return await admin_tools.admin_list_domains()
        elif name == "admin_list_tenants":
            return await admin_tools.admin_list_tenants()
        elif name == "admin_get_tenant":
            return await admin_tools.admin_get_tenant(**arguments)
        elif name == "admin_assign_role":
            return await admin_tools.admin_assign_role(**arguments)
        elif name == "admin_list_roles":
            return await admin_tools.admin_list_roles()
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
        logger.info("Starting admin-mcp server")
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
