"""MCP Server for Data Quality — validation, anomaly detection, and rule management."""

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from src.tools.dataquality_tools import (
    dataquality_create_rule,
    dataquality_delete_rule,
    dataquality_export_report,
    dataquality_get_anomalies,
    dataquality_get_data_profile,
    dataquality_get_metrics,
    dataquality_get_rule,
    dataquality_get_validation_history,
    dataquality_health_check,
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
            description="Create new validation rule for a dataset",
            inputSchema={
                "type": "object",
                "properties": {
                    "dataset_id": {"type": "string"},
                    "rule_name": {"type": "string"},
                    "rule_type": {"type": "string", "description": "Type of rule (null_check, range_check, pattern, etc)"},
                    "config": {"type": "object", "description": "Configuration dict for the rule"},
                },
                "required": ["dataset_id", "rule_name", "rule_type", "config"],
            },
        ),
        Tool(
            name="dataquality_run_validation",
            description="Execute validation against dataset with optional specific rules",
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
            description="Detect and list data anomalies (outliers, drift, etc)",
            inputSchema={
                "type": "object",
                "properties": {
                    "dataset_id": {"type": "string"},
                    "anomaly_type": {"type": "string", "description": "Type filter: outlier, drift, etc"},
                    "limit": {"type": "integer", "default": 100},
                },
                "required": ["dataset_id"],
            },
        ),
        Tool(
            name="dataquality_get_metrics",
            description="Get quality metrics (completeness, accuracy, consistency %)",
            inputSchema={
                "type": "object",
                "properties": {
                    "dataset_id": {"type": "string"},
                    "metric_type": {"type": "string", "description": "Metric type: completeness, accuracy, consistency"},
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
            name="dataquality_get_validation_history",
            description="Get validation history for a dataset",
            inputSchema={
                "type": "object",
                "properties": {
                    "dataset_id": {"type": "string"},
                    "limit": {"type": "integer", "default": 50},
                },
                "required": ["dataset_id"],
            },
        ),
        Tool(
            name="dataquality_get_data_profile",
            description="Get data profile with distributions, outliers, and missing percentages",
            inputSchema={
                "type": "object",
                "properties": {
                    "dataset_id": {"type": "string"},
                    "columns": {"type": "array", "items": {"type": "string"}, "description": "Columns to profile (optional, all if empty)"},
                },
                "required": ["dataset_id"],
            },
        ),
        Tool(
            name="dataquality_export_report",
            description="Export data quality report in pdf, csv, or json format",
            inputSchema={
                "type": "object",
                "properties": {
                    "dataset_id": {"type": "string"},
                    "format": {"type": "string", "enum": ["pdf", "csv", "json"], "default": "pdf"},
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
        Tool(
            name="dataquality_health_check",
            description="Check if platform-dataquality service is healthy",
            inputSchema={"type": "object", "properties": {}},
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
        elif name == "dataquality_get_validation_history":
            result = await dataquality_get_validation_history(
                arguments["dataset_id"],
                arguments.get("limit", 50),
            )
        elif name == "dataquality_get_data_profile":
            result = await dataquality_get_data_profile(
                arguments["dataset_id"],
                arguments.get("columns"),
            )
        elif name == "dataquality_export_report":
            result = await dataquality_export_report(
                arguments["dataset_id"],
                arguments.get("format", "pdf"),
            )
        elif name == "dataquality_get_rule":
            result = await dataquality_get_rule(arguments["rule_id"])
        elif name == "dataquality_delete_rule":
            result = await dataquality_delete_rule(arguments["rule_id"])
        elif name == "dataquality_health_check":
            result = await dataquality_health_check()
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
