"""MCP Server for datalake — dataset operations and schema discovery."""

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from src.tools.datalake_tools import (
    datalake_compute_statistics,
    datalake_create_dataset,
    datalake_get_dataset,
    datalake_get_schema,
    datalake_list_datasets,
    datalake_list_schemas,
    datalake_prepare_for_ml,
    datalake_sample_data,
)

# Initialize MCP server
server = Server("datalake-mcp")


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List available datalake tools."""
    return [
        Tool(
            name="datalake_list_schemas",
            description="List all available schemas in datalake",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="datalake_get_schema",
            description="Get schema details including tables and columns",
            inputSchema={
                "type": "object",
                "properties": {
                    "schema_name": {"type": "string", "description": "Name of the schema"},
                },
                "required": ["schema_name"],
            },
        ),
        Tool(
            name="datalake_list_datasets",
            description="List all available datasets in datalake",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="datalake_get_dataset",
            description="Get dataset details and metadata",
            inputSchema={
                "type": "object",
                "properties": {
                    "dataset_id": {"type": "string", "description": "ID of the dataset"},
                },
                "required": ["dataset_id"],
            },
        ),
        Tool(
            name="datalake_prepare_for_ml",
            description="Prepare dataset for ML training (train/test split, normalization, feature engineering)",
            inputSchema={
                "type": "object",
                "properties": {
                    "dataset_id": {"type": "string", "description": "ID of the dataset"},
                    "model_type": {
                        "type": "string",
                        "description": "Type of ML model (classification, regression, clustering)",
                    },
                },
                "required": ["dataset_id", "model_type"],
            },
        ),
        Tool(
            name="datalake_sample_data",
            description="Get sample of data from dataset",
            inputSchema={
                "type": "object",
                "properties": {
                    "dataset_id": {"type": "string", "description": "ID of the dataset"},
                    "limit": {
                        "type": "integer",
                        "description": "Number of rows to return (default: 10)",
                        "default": 10,
                    },
                },
                "required": ["dataset_id"],
            },
        ),
        Tool(
            name="datalake_create_dataset",
            description="Create new dataset in datalake",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Dataset name"},
                    "schema": {
                        "type": "object",
                        "description": "Dataset schema (column definitions)",
                    },
                    "description": {
                        "type": "string",
                        "description": "Optional description",
                        "default": "",
                    },
                },
                "required": ["name", "schema"],
            },
        ),
        Tool(
            name="datalake_compute_statistics",
            description="Compute statistics for dataset (mean, std, percentiles, distribution)",
            inputSchema={
                "type": "object",
                "properties": {
                    "dataset_id": {"type": "string", "description": "ID of the dataset"},
                },
                "required": ["dataset_id"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Execute a tool and return result as JSON."""
    try:
        if name == "datalake_list_schemas":
            result = await datalake_list_schemas()
        elif name == "datalake_get_schema":
            result = await datalake_get_schema(arguments["schema_name"])
        elif name == "datalake_list_datasets":
            result = await datalake_list_datasets()
        elif name == "datalake_get_dataset":
            result = await datalake_get_dataset(arguments["dataset_id"])
        elif name == "datalake_prepare_for_ml":
            result = await datalake_prepare_for_ml(
                arguments["dataset_id"], arguments["model_type"]
            )
        elif name == "datalake_sample_data":
            limit = arguments.get("limit", 10)
            result = await datalake_sample_data(arguments["dataset_id"], limit)
        elif name == "datalake_create_dataset":
            result = await datalake_create_dataset(
                arguments["name"],
                arguments["schema"],
                arguments.get("description", ""),
            )
        elif name == "datalake_compute_statistics":
            result = await datalake_compute_statistics(arguments["dataset_id"])
        else:
            result = '{"error": "UnknownTool", "details": "Tool not found"}'

        return [TextContent(type="text", text=result)]
    except Exception as e:
        error_json = f'{{"error": "Exception", "details": "{str(e)}"}}'
        return [TextContent(type="text", text=error_json)]


async def main():
    """Run the MCP server."""
    async with stdio_server(server) as streams:
        await streams.wait_closed()


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
