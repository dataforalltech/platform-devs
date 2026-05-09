"""MCP Server for DAI Orchestrator — expose DAI as agent interface."""

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from src.tools.dai_tools import (
    dai_analyze,
    dai_chat,
    dai_execute_workflow,
    dai_generate_workflow,
    dai_get_knowledge_base,
    dai_get_session_history,
)

server = Server("dai-mcp")


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List available DAI tools."""
    return [
        Tool(
            name="dai_chat",
            description="Send message to DAI orchestrator and get response",
            inputSchema={
                "type": "object",
                "properties": {
                    "message": {"type": "string"},
                    "context": {"type": "object"},
                },
                "required": ["message"],
            },
        ),
        Tool(
            name="dai_analyze",
            description="Ask DAI to analyze data for specific objective",
            inputSchema={
                "type": "object",
                "properties": {
                    "objective": {"type": "string"},
                    "data": {"type": "object"},
                },
                "required": ["objective", "data"],
            },
        ),
        Tool(
            name="dai_generate_workflow",
            description="Ask DAI to generate workflow for specific objective",
            inputSchema={
                "type": "object",
                "properties": {
                    "objective": {"type": "string"},
                    "constraints": {"type": "object"},
                },
                "required": ["objective"],
            },
        ),
        Tool(
            name="dai_execute_workflow",
            description="Execute workflow via DAI orchestrator",
            inputSchema={
                "type": "object",
                "properties": {
                    "workflow_id": {"type": "string"},
                    "inputs": {"type": "object"},
                },
                "required": ["workflow_id"],
            },
        ),
        Tool(
            name="dai_get_session_history",
            description="Get session history and memory from DAI",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string"},
                },
                "required": ["session_id"],
            },
        ),
        Tool(
            name="dai_get_knowledge_base",
            description="Query DAI knowledge base (business or technical)",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "kb_type": {
                        "type": "string",
                        "description": "Knowledge base type (business or technical)",
                        "default": "business",
                    },
                },
                "required": ["query"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Execute a tool."""
    try:
        if name == "dai_chat":
            result = await dai_chat(arguments["message"], arguments.get("context"))
        elif name == "dai_analyze":
            result = await dai_analyze(arguments["objective"], arguments["data"])
        elif name == "dai_generate_workflow":
            result = await dai_generate_workflow(
                arguments["objective"],
                arguments.get("constraints"),
            )
        elif name == "dai_execute_workflow":
            result = await dai_execute_workflow(
                arguments["workflow_id"],
                arguments.get("inputs"),
            )
        elif name == "dai_get_session_history":
            result = await dai_get_session_history(arguments["session_id"])
        elif name == "dai_get_knowledge_base":
            result = await dai_get_knowledge_base(
                arguments["query"],
                arguments.get("kb_type", "business"),
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
