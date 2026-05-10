"""MCP Server for DAI Orchestrator — expose DAI as agent interface."""

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from src.tools.dai_tools import (
    dai_analyze,
    dai_audit_log,
    dai_chat,
    dai_execute_workflow,
    dai_generate_workflow,
    dai_get_knowledge_base,
    dai_get_profile,
    dai_get_session_history,
    dai_get_workflow_status,
    dai_list_workflows,
    dai_set_profile,
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
            description="Ask DAI to generate workflow for specific objective with constraints",
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
            description="Execute workflow via DAI orchestrator with inputs",
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
            name="dai_get_workflow_status",
            description="Get workflow execution status (pending|running|completed|failed) with progress and results",
            inputSchema={
                "type": "object",
                "properties": {
                    "execution_id": {"type": "string"},
                },
                "required": ["execution_id"],
            },
        ),
        Tool(
            name="dai_list_workflows",
            description="List all available workflows for a tenant",
            inputSchema={
                "type": "object",
                "properties": {
                    "tenant_id": {"type": "string"},
                },
                "required": ["tenant_id"],
            },
        ),
        Tool(
            name="dai_get_profile",
            description="Get user profile with type, LLM model, risk max level",
            inputSchema={
                "type": "object",
                "properties": {
                    "tenant_id": {"type": "string"},
                    "user_id": {"type": "string"},
                },
                "required": ["tenant_id", "user_id"],
            },
        ),
        Tool(
            name="dai_set_profile",
            description="Set user profile type (data_engineer|analyst|data_scientist|admin)",
            inputSchema={
                "type": "object",
                "properties": {
                    "tenant_id": {"type": "string"},
                    "user_id": {"type": "string"},
                    "profile_type": {
                        "type": "string",
                        "enum": ["data_engineer", "analyst", "data_scientist", "admin"],
                    },
                },
                "required": ["tenant_id", "user_id", "profile_type"],
            },
        ),
        Tool(
            name="dai_get_session_history",
            description="Get session history for a user",
            inputSchema={
                "type": "object",
                "properties": {
                    "tenant_id": {"type": "string"},
                    "user_id": {"type": "string"},
                    "limit": {"type": "integer", "default": 50},
                },
                "required": ["tenant_id", "user_id"],
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
                        "enum": ["business", "technical"],
                        "default": "business",
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="dai_audit_log",
            description="Get audit log with optional action filter",
            inputSchema={
                "type": "object",
                "properties": {
                    "tenant_id": {"type": "string"},
                    "filter_action": {"type": "string", "description": "Filter by action (optional)"},
                    "limit": {"type": "integer", "default": 100},
                },
                "required": ["tenant_id"],
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
        elif name == "dai_get_workflow_status":
            result = await dai_get_workflow_status(arguments["execution_id"])
        elif name == "dai_list_workflows":
            result = await dai_list_workflows(arguments["tenant_id"])
        elif name == "dai_get_profile":
            result = await dai_get_profile(arguments["tenant_id"], arguments["user_id"])
        elif name == "dai_set_profile":
            result = await dai_set_profile(
                arguments["tenant_id"],
                arguments["user_id"],
                arguments["profile_type"],
            )
        elif name == "dai_get_session_history":
            result = await dai_get_session_history(
                arguments["tenant_id"],
                arguments["user_id"],
                arguments.get("limit", 50),
            )
        elif name == "dai_get_knowledge_base":
            result = await dai_get_knowledge_base(
                arguments["query"],
                arguments.get("kb_type", "business"),
            )
        elif name == "dai_audit_log":
            result = await dai_audit_log(
                arguments["tenant_id"],
                arguments.get("filter_action"),
                arguments.get("limit", 100),
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
