"""MCP server implementation for platform-connectors."""

import asyncio
import json
import logging
from typing import Any

from mcp.server import Server
from mcp.types import TextContent, Tool

from ..config.settings import Settings
from ..tools import connectors_tools

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

settings = Settings()
server = Server("connectors-mcp")


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List all available tools."""
    return [
        Tool(
            name="connectors_health_check",
            description="Check if platform-connectors service is healthy",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
        Tool(
            name="connectors_list",
            description="List all available connectors (40+ adapters)",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
        Tool(
            name="connectors_get",
            description="Get a specific connector by ID",
            inputSchema={
                "type": "object",
                "properties": {
                    "connector_id": {
                        "type": "string",
                        "description": "The connector identifier",
                    }
                },
                "required": ["connector_id"],
            },
        ),
        Tool(
            name="connectors_search",
            description="Search connectors by name or query",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query string",
                    }
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="connectors_get_schema",
            description="Get configuration schema for a connector",
            inputSchema={
                "type": "object",
                "properties": {
                    "connector_id": {
                        "type": "string",
                        "description": "The connector identifier",
                    }
                },
                "required": ["connector_id"],
            },
        ),
        Tool(
            name="connectors_test_connection",
            description="Test connection with provided credentials",
            inputSchema={
                "type": "object",
                "properties": {
                    "connector_id": {
                        "type": "string",
                        "description": "The connector identifier",
                    },
                    "credentials": {
                        "type": "object",
                        "description": "Configuration/credentials to test",
                    },
                },
                "required": ["connector_id", "credentials"],
            },
        ),
        Tool(
            name="connectors_list_credentials",
            description="List user's stored connector credentials",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
        Tool(
            name="connectors_get_credential",
            description="Get a specific credential by ID",
            inputSchema={
                "type": "object",
                "properties": {
                    "credential_id": {
                        "type": "string",
                        "description": "The credential identifier",
                    }
                },
                "required": ["credential_id"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Call a tool by name with the given arguments."""
    try:
        logger.info(f"Calling tool: {name}")

        if name == "connectors_health_check":
            return await connectors_tools.connectors_health_check()
        elif name == "connectors_list":
            return await connectors_tools.connectors_list()
        elif name == "connectors_get":
            return await connectors_tools.connectors_get(**arguments)
        elif name == "connectors_search":
            return await connectors_tools.connectors_search(**arguments)
        elif name == "connectors_get_schema":
            return await connectors_tools.connectors_get_schema(**arguments)
        elif name == "connectors_test_connection":
            return await connectors_tools.connectors_test_connection(**arguments)
        elif name == "connectors_list_credentials":
            return await connectors_tools.connectors_list_credentials()
        elif name == "connectors_get_credential":
            return await connectors_tools.connectors_get_credential(**arguments)
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
        logger.info("Starting connectors-mcp server")
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
