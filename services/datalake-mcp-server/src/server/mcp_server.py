"""MCP Server for datalake — 8 core tools for database and table operations."""

import json
import logging
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from src.config.settings import settings
from src.tools.datalake_tools import (
    create_table,
    drop_table,
    get_table_schema,
    get_table_stats,
    list_schemas,
    list_tables,
    query_data,
    validate_table,
)

logger = logging.getLogger(__name__)

# Initialize MCP server
server = Server("datalake-mcp")


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List available datalake tools."""
    return [
        Tool(
            name="list_schemas",
            description="List all schemas in a database",
            inputSchema={
                "type": "object",
                "properties": {
                    "database": {"type": "string", "description": "Database name"},
                },
                "required": ["database"],
            },
        ),
        Tool(
            name="list_tables",
            description="List all tables in a schema",
            inputSchema={
                "type": "object",
                "properties": {
                    "database": {"type": "string", "description": "Database name"},
                    "schema": {"type": "string", "description": "Schema name"},
                },
                "required": ["database", "schema"],
            },
        ),
        Tool(
            name="get_table_schema",
            description="Get column definitions for a table",
            inputSchema={
                "type": "object",
                "properties": {
                    "database": {"type": "string", "description": "Database name"},
                    "schema": {"type": "string", "description": "Schema name"},
                    "table": {"type": "string", "description": "Table name"},
                },
                "required": ["database", "schema", "table"],
            },
        ),
        Tool(
            name="create_table",
            description="Create a new table with specified columns",
            inputSchema={
                "type": "object",
                "properties": {
                    "database": {"type": "string", "description": "Database name"},
                    "schema": {"type": "string", "description": "Schema name"},
                    "table": {"type": "string", "description": "Table name"},
                    "columns": {
                        "type": "array",
                        "description": "List of columns {name, type, nullable}",
                        "items": {"type": "object"},
                    },
                },
                "required": ["database", "schema", "table", "columns"],
            },
        ),
        Tool(
            name="drop_table",
            description="Drop (delete) a table",
            inputSchema={
                "type": "object",
                "properties": {
                    "database": {"type": "string", "description": "Database name"},
                    "schema": {"type": "string", "description": "Schema name"},
                    "table": {"type": "string", "description": "Table name"},
                },
                "required": ["database", "schema", "table"],
            },
        ),
        Tool(
            name="query_data",
            description="Execute a SQL query and return data",
            inputSchema={
                "type": "object",
                "properties": {
                    "database": {"type": "string", "description": "Database name"},
                    "sql": {"type": "string", "description": "SQL query string"},
                    "limit": {
                        "type": "integer",
                        "description": "Maximum rows to return",
                        "default": 1000,
                    },
                },
                "required": ["database", "sql"],
            },
        ),
        Tool(
            name="validate_table",
            description="Validate table integrity and constraints",
            inputSchema={
                "type": "object",
                "properties": {
                    "database": {"type": "string", "description": "Database name"},
                    "schema": {"type": "string", "description": "Schema name"},
                    "table": {"type": "string", "description": "Table name"},
                },
                "required": ["database", "schema", "table"],
            },
        ),
        Tool(
            name="get_table_stats",
            description="Get statistics for a table (rows, columns, size)",
            inputSchema={
                "type": "object",
                "properties": {
                    "database": {"type": "string", "description": "Database name"},
                    "schema": {"type": "string", "description": "Schema name"},
                    "table": {"type": "string", "description": "Table name"},
                },
                "required": ["database", "schema", "table"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Execute a tool and return result as JSON."""
    logger.debug(f"Calling tool: {name} with args: {arguments}")
    try:
        if name == "list_schemas":
            result = await list_schemas(arguments["database"])
        elif name == "list_tables":
            result = await list_tables(arguments["database"], arguments["schema"])
        elif name == "get_table_schema":
            result = await get_table_schema(
                arguments["database"], arguments["schema"], arguments["table"]
            )
        elif name == "create_table":
            result = await create_table(
                arguments["database"],
                arguments["schema"],
                arguments["table"],
                arguments["columns"],
            )
        elif name == "drop_table":
            result = await drop_table(
                arguments["database"], arguments["schema"], arguments["table"]
            )
        elif name == "query_data":
            limit = arguments.get("limit", 1000)
            result = await query_data(arguments["database"], arguments["sql"], limit)
        elif name == "validate_table":
            result = await validate_table(
                arguments["database"], arguments["schema"], arguments["table"]
            )
        elif name == "get_table_stats":
            result = await get_table_stats(
                arguments["database"], arguments["schema"], arguments["table"]
            )
        else:
            result = json.dumps(
                {"error": "ToolNotFound", "details": f"Tool '{name}' not found"}
            )

        return [TextContent(type="text", text=result)]
    except Exception as e:
        logger.exception(f"Error calling tool {name}")
        error_json = json.dumps({"error": "Exception", "details": str(e)})
        return [TextContent(type="text", text=error_json)]


async def main():
    """Run the MCP server."""
    logging.basicConfig(
        level=settings.MCP_DATALAKE_LOG_LEVEL if hasattr(settings, 'MCP_DATALAKE_LOG_LEVEL') else 'INFO',
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    logger.info("Starting datalake-mcp server")
    async with stdio_server(server) as streams:
        await streams.wait_closed()


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
