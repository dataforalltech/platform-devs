"""MCP Server for Pipeline — orchestration and execution."""

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from src.tools.pipeline_tools import (
    pipeline_cancel_run,
    pipeline_create_pipeline,
    pipeline_delete_pipeline,
    pipeline_get_pipeline,
    pipeline_get_pipeline_logs,
    pipeline_get_run_history,
    pipeline_get_run_status,
    pipeline_list_pipelines,
    pipeline_trigger_run,
)

server = Server("pipeline-mcp")


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List available pipeline tools."""
    return [
        Tool(
            name="pipeline_create_pipeline",
            description="Create new pipeline",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "config": {"type": "object"},
                },
                "required": ["name", "config"],
            },
        ),
        Tool(
            name="pipeline_get_pipeline",
            description="Get pipeline details",
            inputSchema={
                "type": "object",
                "properties": {
                    "pipeline_id": {"type": "string"},
                },
                "required": ["pipeline_id"],
            },
        ),
        Tool(
            name="pipeline_list_pipelines",
            description="List all pipelines",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="pipeline_trigger_run",
            description="Trigger pipeline execution",
            inputSchema={
                "type": "object",
                "properties": {
                    "pipeline_id": {"type": "string"},
                    "inputs": {"type": "object"},
                },
                "required": ["pipeline_id"],
            },
        ),
        Tool(
            name="pipeline_get_run_status",
            description="Get pipeline run status",
            inputSchema={
                "type": "object",
                "properties": {
                    "run_id": {"type": "string"},
                },
                "required": ["run_id"],
            },
        ),
        Tool(
            name="pipeline_get_pipeline_logs",
            description="Get pipeline execution logs",
            inputSchema={
                "type": "object",
                "properties": {
                    "pipeline_id": {"type": "string"},
                    "run_id": {"type": "string"},
                },
                "required": ["pipeline_id"],
            },
        ),
        Tool(
            name="pipeline_cancel_run",
            description="Cancel pipeline run",
            inputSchema={
                "type": "object",
                "properties": {
                    "run_id": {"type": "string"},
                },
                "required": ["run_id"],
            },
        ),
        Tool(
            name="pipeline_delete_pipeline",
            description="Delete pipeline",
            inputSchema={
                "type": "object",
                "properties": {
                    "pipeline_id": {"type": "string"},
                },
                "required": ["pipeline_id"],
            },
        ),
        Tool(
            name="pipeline_get_run_history",
            description="Get execution history for pipeline",
            inputSchema={
                "type": "object",
                "properties": {
                    "pipeline_id": {"type": "string"},
                    "limit": {"type": "integer", "default": 20},
                },
                "required": ["pipeline_id"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Execute a tool."""
    try:
        if name == "pipeline_create_pipeline":
            result = await pipeline_create_pipeline(arguments["name"], arguments["config"])
        elif name == "pipeline_get_pipeline":
            result = await pipeline_get_pipeline(arguments["pipeline_id"])
        elif name == "pipeline_list_pipelines":
            result = await pipeline_list_pipelines()
        elif name == "pipeline_trigger_run":
            result = await pipeline_trigger_run(arguments["pipeline_id"], arguments.get("inputs"))
        elif name == "pipeline_get_run_status":
            result = await pipeline_get_run_status(arguments["run_id"])
        elif name == "pipeline_get_pipeline_logs":
            result = await pipeline_get_pipeline_logs(arguments["pipeline_id"], arguments.get("run_id"))
        elif name == "pipeline_cancel_run":
            result = await pipeline_cancel_run(arguments["run_id"])
        elif name == "pipeline_delete_pipeline":
            result = await pipeline_delete_pipeline(arguments["pipeline_id"])
        elif name == "pipeline_get_run_history":
            result = await pipeline_get_run_history(arguments["pipeline_id"], arguments.get("limit", 20))
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
