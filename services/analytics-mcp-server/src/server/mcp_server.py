"""MCP Server for Analytics — dashboards, reports, and BI operations."""

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from src.tools.analytics_tools import (
    analytics_create_report,
    analytics_delete_report,
    analytics_execute_query,
    analytics_get_dashboard,
    analytics_get_report,
    analytics_list_dashboards,
    analytics_list_reports,
)

server = Server("analytics-mcp")


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List available analytics tools."""
    return [
        Tool(
            name="analytics_list_dashboards",
            description="List all dashboards",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="analytics_get_dashboard",
            description="Get dashboard details and metadata",
            inputSchema={
                "type": "object",
                "properties": {
                    "dashboard_id": {"type": "string"},
                },
                "required": ["dashboard_id"],
            },
        ),
        Tool(
            name="analytics_create_report",
            description="Create new analytics report",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "query": {"type": "string"},
                    "dashboard_id": {"type": "string"},
                },
                "required": ["name", "query"],
            },
        ),
        Tool(
            name="analytics_execute_query",
            description="Execute analytics query",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="analytics_list_reports",
            description="List all analytics reports",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="analytics_get_report",
            description="Get report details",
            inputSchema={
                "type": "object",
                "properties": {
                    "report_id": {"type": "string"},
                },
                "required": ["report_id"],
            },
        ),
        Tool(
            name="analytics_delete_report",
            description="Delete analytics report",
            inputSchema={
                "type": "object",
                "properties": {
                    "report_id": {"type": "string"},
                },
                "required": ["report_id"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Execute a tool."""
    try:
        if name == "analytics_list_dashboards":
            result = await analytics_list_dashboards()
        elif name == "analytics_get_dashboard":
            result = await analytics_get_dashboard(arguments["dashboard_id"])
        elif name == "analytics_create_report":
            result = await analytics_create_report(
                arguments["name"],
                arguments["query"],
                arguments.get("dashboard_id"),
            )
        elif name == "analytics_execute_query":
            result = await analytics_execute_query(arguments["query"])
        elif name == "analytics_list_reports":
            result = await analytics_list_reports()
        elif name == "analytics_get_report":
            result = await analytics_get_report(arguments["report_id"])
        elif name == "analytics_delete_report":
            result = await analytics_delete_report(arguments["report_id"])
        else:
            result = '{"error": "UnknownTool", "details": "Tool not found"}'

        return [TextContent(type="text", text=result)]
    except Exception as e:
        return [TextContent(type="text", text=f'{{"error": "Exception", "details": "{str(e)}"}}')]


async def main():
    """Run the MCP server."""
    async with stdio_server(server) as streams:
        await streams.wait_closed()


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
