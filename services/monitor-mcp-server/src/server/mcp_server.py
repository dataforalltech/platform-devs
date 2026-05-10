"""MCP Server for Monitor — service monitoring, alerts, and health checks."""

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from src.tools.monitor_tools import (
    monitor_acknowledge_alert,
    monitor_create_alert_rule,
    monitor_get_alert,
    monitor_get_health_status,
    monitor_get_metrics,
    monitor_get_performance_report,
    monitor_get_service_logs,
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
            description="Get service metrics (cpu %, memory %, disk %, network Mbps)",
            inputSchema={
                "type": "object",
                "properties": {
                    "service_name": {"type": "string"},
                    "metric_type": {
                        "type": "string",
                        "description": "Metric type (cpu, memory, disk, network)",
                        "enum": ["cpu", "memory", "disk", "network"],
                    },
                    "time_range": {
                        "type": "string",
                        "description": "Time range (1h, 24h, 7d)",
                        "default": "1h",
                    },
                },
                "required": ["service_name"],
            },
        ),
        Tool(
            name="monitor_get_health_status",
            description="Get service health status (healthy|degraded|down) with uptime % and response time ms",
            inputSchema={
                "type": "object",
                "properties": {
                    "service_name": {"type": "string"},
                },
                "required": ["service_name"],
            },
        ),
        Tool(
            name="monitor_list_alerts",
            description="List alerts with optional filters",
            inputSchema={
                "type": "object",
                "properties": {
                    "service_name": {"type": "string", "description": "Filter by service (optional)"},
                    "severity": {
                        "type": "string",
                        "description": "Filter by severity: critical, high, medium, low (optional)",
                        "enum": ["critical", "high", "medium", "low"],
                    },
                },
            },
        ),
        Tool(
            name="monitor_get_alert",
            description="Get alert details by ID",
            inputSchema={
                "type": "object",
                "properties": {
                    "alert_id": {"type": "string"},
                },
                "required": ["alert_id"],
            },
        ),
        Tool(
            name="monitor_create_alert_rule",
            description="Create new alert rule with condition and threshold",
            inputSchema={
                "type": "object",
                "properties": {
                    "service_name": {"type": "string"},
                    "condition": {"type": "string", "description": "Condition (e.g., cpu_usage_high, memory_threshold_exceeded)"},
                    "threshold": {"type": "number", "description": "Threshold value for the condition"},
                },
                "required": ["service_name", "condition", "threshold"],
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
        Tool(
            name="monitor_get_service_logs",
            description="Get service logs filtered by level",
            inputSchema={
                "type": "object",
                "properties": {
                    "service_name": {"type": "string"},
                    "level": {
                        "type": "string",
                        "description": "Log level (debug, info, warning, error, critical)",
                        "enum": ["debug", "info", "warning", "error", "critical"],
                        "default": "info",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of logs to return",
                        "default": 100,
                    },
                },
                "required": ["service_name"],
            },
        ),
        Tool(
            name="monitor_get_performance_report",
            description="Get comprehensive performance report with summary, trends, and anomalies",
            inputSchema={
                "type": "object",
                "properties": {
                    "service_name": {"type": "string"},
                    "time_range": {
                        "type": "string",
                        "description": "Time range (1h, 24h, 7d)",
                        "default": "24h",
                    },
                },
                "required": ["service_name"],
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
                arguments.get("time_range", "1h"),
            )
        elif name == "monitor_get_health_status":
            result = await monitor_get_health_status(arguments["service_name"])
        elif name == "monitor_list_alerts":
            result = await monitor_list_alerts(
                arguments.get("service_name"),
                arguments.get("severity"),
            )
        elif name == "monitor_get_alert":
            result = await monitor_get_alert(arguments["alert_id"])
        elif name == "monitor_create_alert_rule":
            result = await monitor_create_alert_rule(
                arguments["service_name"],
                arguments["condition"],
                arguments["threshold"],
            )
        elif name == "monitor_acknowledge_alert":
            result = await monitor_acknowledge_alert(arguments["alert_id"])
        elif name == "monitor_get_service_logs":
            result = await monitor_get_service_logs(
                arguments["service_name"],
                arguments.get("level", "info"),
                arguments.get("limit", 100),
            )
        elif name == "monitor_get_performance_report":
            result = await monitor_get_performance_report(
                arguments["service_name"],
                arguments.get("time_range", "24h"),
            )
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
