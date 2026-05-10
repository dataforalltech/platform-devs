"""MCP Server for Analytics — 7 core tools for dashboards and metrics."""

import json
import logging
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from src.config.settings import settings
from src.tools.analytics_tools import (
    create_dashboard,
    export_dashboard,
    get_dashboard,
    get_metrics,
    list_dashboards,
    query_data,
    refresh_dashboard,
)

logger = logging.getLogger(__name__)

server = Server("analytics-mcp")


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List available analytics tools."""
    return [
        Tool(
            name="list_dashboards",
            description="List all dashboards for a tenant",
            inputSchema={
                "type": "object",
                "properties": {
                    "tenant_id": {"type": "string", "description": "Tenant identifier"},
                },
                "required": ["tenant_id"],
            },
        ),
        Tool(
            name="get_dashboard",
            description="Get dashboard details",
            inputSchema={
                "type": "object",
                "properties": {
                    "dashboard_id": {"type": "string", "description": "Dashboard identifier"},
                },
                "required": ["dashboard_id"],
            },
        ),
        Tool(
            name="create_dashboard",
            description="Create a new dashboard",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Dashboard name"},
                    "description": {"type": "string", "description": "Dashboard description"},
                    "layout": {
                        "type": "object",
                        "description": "Dashboard layout configuration",
                    },
                },
                "required": ["name", "description", "layout"],
            },
        ),
        Tool(
            name="refresh_dashboard",
            description="Refresh dashboard data",
            inputSchema={
                "type": "object",
                "properties": {
                    "dashboard_id": {"type": "string", "description": "Dashboard identifier"},
                },
                "required": ["dashboard_id"],
            },
        ),
        Tool(
            name="get_metrics",
            description="Get metrics data for a dashboard",
            inputSchema={
                "type": "object",
                "properties": {
                    "dashboard_id": {"type": "string", "description": "Dashboard identifier"},
                    "metric_name": {"type": "string", "description": "Metric name"},
                    "time_range": {
                        "type": "string",
                        "description": "Time range (24h, 7d, 30d)",
                    },
                },
                "required": ["dashboard_id", "metric_name", "time_range"],
            },
        ),
        Tool(
            name="query_data",
            description="Execute analytics query",
            inputSchema={
                "type": "object",
                "properties": {
                    "sql": {"type": "string", "description": "SQL query"},
                    "limit": {
                        "type": "integer",
                        "description": "Maximum rows to return",
                        "default": 1000,
                    },
                },
                "required": ["sql"],
            },
        ),
        Tool(
            name="export_dashboard",
            description="Export dashboard to file",
            inputSchema={
                "type": "object",
                "properties": {
                    "dashboard_id": {"type": "string", "description": "Dashboard identifier"},
                    "format": {
                        "type": "string",
                        "description": "Export format (pdf, png, csv, json)",
                        "default": "pdf",
                    },
                },
                "required": ["dashboard_id"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Execute a tool and return result as JSON."""
    logger.debug(f"Calling tool: {name} with args: {arguments}")
    try:
        if name == "list_dashboards":
            result = await list_dashboards(arguments["tenant_id"])
        elif name == "get_dashboard":
            result = await get_dashboard(arguments["dashboard_id"])
        elif name == "create_dashboard":
            result = await create_dashboard(
                arguments["name"],
                arguments["description"],
                arguments["layout"],
            )
        elif name == "refresh_dashboard":
            result = await refresh_dashboard(arguments["dashboard_id"])
        elif name == "get_metrics":
            result = await get_metrics(
                arguments["dashboard_id"],
                arguments["metric_name"],
                arguments["time_range"],
            )
        elif name == "query_data":
            limit = arguments.get("limit", 1000)
            result = await query_data(arguments["sql"], limit)
        elif name == "export_dashboard":
            format_type = arguments.get("format", "pdf")
            result = await export_dashboard(arguments["dashboard_id"], format_type)
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
        level=settings.MCP_ANALYTICS_LOG_LEVEL if hasattr(settings, 'MCP_ANALYTICS_LOG_LEVEL') else 'INFO',
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    logger.info("Starting analytics-mcp server")
    async with stdio_server(server) as streams:
        await streams.wait_closed()


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
