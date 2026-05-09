"""MCP Server for Data Quality — validation, anomaly detection, and rule management."""

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from src.tools.dataquality_tools import (
    dataquality_create_rule,
    dataquality_delete_rule,
    dataquality_get_anomalies,
    dataquality_get_metrics,
    dataquality_get_rule,
    dataquality_list_rules,
    dataquality_run_validation,
    dataquality_validate_dataset,
)

server = Server("dataquality-mcp")


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List available data quality tools."""
    return [
        Tool(
            name="dataquality_list_rules",
            description="List all validation rules",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="dataquality_create_rule",
            description="Create new validation rule",
            inputSchema={
                "type": "object",
                "properties": {
                    "dataset_id": {"type": "string"},
                    "rule_name": {"type": "string"},
                    "rule_type": {"type": "string"},
                    "config": {"type": "object"},
                },
                "required": ["dataset_id", "rule_name", "rule_type", "config"],
            },
        ),
        Tool(
            name="dataquality_run_validation",
            description="Execute validation against dataset",
            inputSchema={
                "type": "object",
                "properties": {
                    "dataset_id": {"type": "string"},
                    "rule_ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["dataset_id"],
            },
        ),
        Tool(
            name="dataquality_get_anomalies",
            description="Detect and list data anomalies",
            inputSchema={
                "type": "object",
                "properties": {
                    "dataset_id": {"type": "string"},
                    "anomaly_type": {"type": "string"},
                    "limit": {"type": "integer", "default": 100},
                },
                "required": ["dataset_id"],
            },
        ),
        Tool(
            name="dataquality_get_metrics",
            description="Get quality metrics and statistics for dataset",
            inputSchema={
                "type": "object",
                "properties": {
                    "dataset_id": {"type": "string"},
                    "metric_type": {"type": "string"},
                },
                "required": ["dataset_id"],
            },
        ),
        Tool(
            name="dataquality_validate_dataset",
            description="Perform full dataset validation including rules and anomalies",
            inputSchema={
                "type": "object",
                "properties": {
                    "dataset_id": {"type": "string"},
                    "include_anomalies": {"type": "boolean", "default": False},
                },
                "required": ["dataset_id"],
            },
        ),
        Tool(
            name="dataquality_get_rule",
            description="Get validation rule details",
            inputSchema={
                "type": "object",
                "properties": {
                    "rule_id": {"type": "string"},
                },
                "required": ["rule_id"],
            },
        ),
        Tool(
            name="dataquality_delete_rule",
            description="Delete validation rule",
            inputSchema={
                "type": "object",
                "properties": {
                    "rule_id": {"type": "string"},
                },
                "required": ["rule_id"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Execute a tool."""
    try:
        if name == "dataquality_list_rules":
            result = await dataquality_list_rules()
        elif name == "dataquality_create_rule":
            result = await dataquality_create_rule(
                arguments["dataset_id"],
                arguments["rule_name"],
                arguments["rule_type"],
                arguments["config"],
            )
        elif name == "dataquality_run_validation":
            result = await dataquality_run_validation(
                arguments["dataset_id"],
                arguments.get("rule_ids"),
            )
        elif name == "dataquality_get_anomalies":
            result = await dataquality_get_anomalies(
                arguments["dataset_id"],
                arguments.get("anomaly_type"),
                arguments.get("limit", 100),
            )
        elif name == "dataquality_get_metrics":
            result = await dataquality_get_metrics(
                arguments["dataset_id"],
                arguments.get("metric_type"),
            )
        elif name == "dataquality_validate_dataset":
            result = await dataquality_validate_dataset(
                arguments["dataset_id"],
                arguments.get("include_anomalies", False),
            )
        elif name == "dataquality_get_rule":
            result = await dataquality_get_rule(arguments["rule_id"])
        elif name == "dataquality_delete_rule":
            result = await dataquality_delete_rule(arguments["rule_id"])
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
