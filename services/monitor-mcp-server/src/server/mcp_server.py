"""MCP Server for Monitor — service monitoring, alerts, and health checks."""

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from src.tools.monitor_tools import (
    monitor_acknowledge_alert,
    monitor_get_alert,
    monitor_get_metrics,
    monitor_get_service_status,
    monitor_list_alerts,
    monitor_list_services,
)

server = Server("monitor-mcp")


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List available monitor tools."""
    return [
        Tool(
            name="monitor_get_service_status",
            description="Get service health status",
            inputSchema={
                "type": "object",
                "properties": {
                    "service_name": {"type": "string"},
                },
                "required": ["service_name"],
            },
        ),
        Tool(
            name="monitor_list_services",
            description="List all monitored services",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="monitor_get_metrics",
            description="Get service metrics (cpu, memory, latency, etc.)",
            inputSchema={
                "type": "object",
                "properties": {
                    "service_name": {"type": "string"},
                    "metric_type": {
                        "type": "string",
                        "description": "Metric type (cpu, memory, latency, throughput)",
                    },
                },
                "required": ["service_name"],
            },
        ),
        Tool(
            name="monitor_list_alerts",
            description="List all active alerts",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="monitor_get_alert",
            description="Get alert details",
            inputSchema={
                "type": "object",
                "properties": {
                    "alert_id": {"type": "string"},
                },
                "required": ["alert_id"],
            },
        ),
        Tool(
            name="monitor_acknowledge_alert",
            description="Acknowledge alert",
            inputSchema={
                "type": "object",
                "properties": {
                    "alert_id": {"type": "string"},
                },
                "required": ["alert_id"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Execute a tool."""
    try:
        if name == "monitor_get_service_status":
            result = await monitor_get_service_status(arguments["service_name"])
        elif name == "monitor_list_services":
            result = await monitor_list_services()
        elif name == "monitor_get_metrics":
            result = await monitor_get_metrics(
                arguments["service_name"],
                arguments.get("metric_type", "cpu"),
            )
        elif name == "monitor_list_alerts":
            result = await monitor_list_alerts()
        elif name == "monitor_get_alert":
            result = await monitor_get_alert(arguments["alert_id"])
        elif name == "monitor_acknowledge_alert":
            result = await monitor_acknowledge_alert(arguments["alert_id"])
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
