"""MCP server implementation for platform-auth."""

import asyncio
import json
import logging
from typing import Any

from mcp.server import Server
from mcp.types import TextContent, Tool

from ..config.settings import Settings
from ..tools import auth_tools

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

settings = Settings()
server = Server("auth-mcp")


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List all available tools."""
    return [
        Tool(
            name="auth_health_check",
            description="Check if platform-auth service is healthy",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
        Tool(
            name="auth_check_email",
            description="Determine authentication type for an email (SSO or password)",
            inputSchema={
                "type": "object",
                "properties": {
                    "email": {
                        "type": "string",
                        "description": "User email address",
                    }
                },
                "required": ["email"],
            },
        ),
        Tool(
            name="auth_list_tenants",
            description="List available tenants for login",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
        Tool(
            name="auth_login",
            description="Authenticate user with email and password",
            inputSchema={
                "type": "object",
                "properties": {
                    "email": {
                        "type": "string",
                        "description": "User email",
                    },
                    "password": {
                        "type": "string",
                        "description": "User password",
                    },
                    "tenant_id": {
                        "type": "string",
                        "description": "Optional tenant ID",
                    },
                },
                "required": ["email", "password"],
            },
        ),
        Tool(
            name="auth_get_me",
            description="Get current authenticated user info",
            inputSchema={
                "type": "object",
                "properties": {
                    "authorization": {
                        "type": "string",
                        "description": "Bearer token (e.g., 'Bearer eyJ...')",
                    }
                },
                "required": ["authorization"],
            },
        ),
        Tool(
            name="auth_get_permissions",
            description="Get current user's permissions and access profile",
            inputSchema={
                "type": "object",
                "properties": {
                    "authorization": {
                        "type": "string",
                        "description": "Bearer token (e.g., 'Bearer eyJ...')",
                    }
                },
                "required": ["authorization"],
            },
        ),
        Tool(
            name="auth_refresh_token",
            description="Refresh access token using refresh token",
            inputSchema={
                "type": "object",
                "properties": {
                    "refresh_token": {
                        "type": "string",
                        "description": "The refresh token",
                    }
                },
                "required": ["refresh_token"],
            },
        ),
        Tool(
            name="auth_logout",
            description="Revoke refresh token and logout user",
            inputSchema={
                "type": "object",
                "properties": {
                    "refresh_token": {
                        "type": "string",
                        "description": "The refresh token to revoke",
                    }
                },
                "required": ["refresh_token"],
            },
        ),
        Tool(
            name="auth_get_service_token",
            description="Get service-to-service authentication token",
            inputSchema={
                "type": "object",
                "properties": {
                    "service_id": {
                        "type": "string",
                        "description": "Service identifier",
                    },
                    "service_secret": {
                        "type": "string",
                        "description": "Service secret/password",
                    },
                },
                "required": ["service_id", "service_secret"],
            },
        ),
        Tool(
            name="auth_validate_token",
            description="Validate a bearer token and extract claims",
            inputSchema={
                "type": "object",
                "properties": {
                    "authorization": {
                        "type": "string",
                        "description": "Bearer token (e.g., 'Bearer eyJ...')",
                    }
                },
                "required": ["authorization"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Call a tool by name with the given arguments."""
    try:
        logger.info(f"Calling tool: {name}")

        if name == "auth_health_check":
            return await auth_tools.auth_health_check()
        elif name == "auth_check_email":
            return await auth_tools.auth_check_email(**arguments)
        elif name == "auth_list_tenants":
            return await auth_tools.auth_list_tenants()
        elif name == "auth_login":
            return await auth_tools.auth_login(**arguments)
        elif name == "auth_get_me":
            return await auth_tools.auth_get_me(**arguments)
        elif name == "auth_get_permissions":
            return await auth_tools.auth_get_permissions(**arguments)
        elif name == "auth_refresh_token":
            return await auth_tools.auth_refresh_token(**arguments)
        elif name == "auth_logout":
            return await auth_tools.auth_logout(**arguments)
        elif name == "auth_get_service_token":
            return await auth_tools.auth_get_service_token(**arguments)
        elif name == "auth_validate_token":
            return await auth_tools.auth_validate_token(**arguments)
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
        logger.info("Starting auth-mcp server")
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
