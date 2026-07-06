from mcp.server import Server
from mcp.types import Tool

server = Server("scheduler-mcp")

@server.list_tools()
async def list_tools():
    return [
        Tool(name="scheduler_health_check", description="Check service health"),
        Tool(name="scheduler_list_jobs", description="List all scheduled jobs"),
        Tool(name="scheduler_get_job", description="Get job by ID"),
        Tool(name="scheduler_create_job", description="Create new job"),
        Tool(name="scheduler_update_job", description="Update job"),
        Tool(name="scheduler_delete_job", description="Delete job"),
        Tool(name="scheduler_trigger_job", description="Trigger job manually"),
    ]

@server.call_tool()
async def call_tool(name: str, arguments: dict):
    if name == "scheduler_health_check":
        return [{"type": "text", "text": '{"status": "ok"}'}]
    else:
        return [{"type": "text", "text": f"Tool {name} not yet implemented"}]

if __name__ == "__main__":
    import asyncio
    asyncio.run(server.run_stdio())
