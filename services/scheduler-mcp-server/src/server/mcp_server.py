"""MCP server implementation for platform-scheduler."""

import asyncio
import json
import logging
from typing import Any

from mcp.server import Server
from mcp.types import TextContent, Tool

from ..config.settings import Settings
from ..tools import scheduler_tools

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

settings = Settings()
server = Server("scheduler-mcp")


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List all available tools."""
    return [
        Tool(
            name="scheduler_health_check",
            description="Check if platform-scheduler service is healthy",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
        Tool(
            name="scheduler_list_tasks",
            description="List all scheduler tasks",
            inputSchema={
                "type": "object",
                "properties": {
                    "tenant_id": {
                        "type": "string",
                        "description": "Optional tenant ID filter",
                    }
                },
                "required": [],
            },
        ),
        Tool(
            name="scheduler_get_task",
            description="Get details of a specific scheduler task",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "The task ID",
                    }
                },
                "required": ["task_id"],
            },
        ),
        Tool(
            name="scheduler_create_task",
            description="Create a new scheduler task with cron expression",
            inputSchema={
                "type": "object",
                "properties": {
                    "cron_expression": {
                        "type": "string",
                        "description": "Cron expression for task scheduling",
                    },
                    "command": {
                        "type": "string",
                        "description": "Command to execute",
                    },
                    "tenant_id": {
                        "type": "string",
                        "description": "Tenant ID for multi-tenancy",
                    },
                    "name": {
                        "type": "string",
                        "description": "Optional task name",
                    },
                    "description": {
                        "type": "string",
                        "description": "Optional task description",
                    },
                },
                "required": ["cron_expression", "command", "tenant_id"],
            },
        ),
        Tool(
            name="scheduler_update_task",
            description="Update an existing scheduler task",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "The task ID to update",
                    },
                    "cron_expression": {
                        "type": "string",
                        "description": "Optional new cron expression",
                    },
                    "command": {
                        "type": "string",
                        "description": "Optional new command",
                    },
                    "name": {
                        "type": "string",
                        "description": "Optional new task name",
                    },
                    "description": {
                        "type": "string",
                        "description": "Optional new task description",
                    },
                },
                "required": ["task_id"],
            },
        ),
        Tool(
            name="scheduler_run_task",
            description="Execute a task immediately",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "The task ID to execute",
                    }
                },
                "required": ["task_id"],
            },
        ),
        Tool(
            name="scheduler_get_task_history",
            description="Get execution history of a task",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "The task ID",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of history records (default: 10)",
                    },
                },
                "required": ["task_id"],
            },
        ),
        Tool(
            name="scheduler_list_schedules",
            description="List all active schedules",
            inputSchema={
                "type": "object",
                "properties": {
                    "tenant_id": {
                        "type": "string",
                        "description": "Optional tenant ID filter",
                    }
                },
                "required": [],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Call a tool by name with the given arguments."""
    try:
        logger.info(f"Calling tool: {name}")

        if name == "scheduler_health_check":
            return await scheduler_tools.scheduler_health_check()
        elif name == "scheduler_list_tasks":
            return await scheduler_tools.scheduler_list_tasks(**arguments)
        elif name == "scheduler_get_task":
            return await scheduler_tools.scheduler_get_task(**arguments)
        elif name == "scheduler_create_task":
            return await scheduler_tools.scheduler_create_task(**arguments)
        elif name == "scheduler_update_task":
            return await scheduler_tools.scheduler_update_task(**arguments)
        elif name == "scheduler_run_task":
            return await scheduler_tools.scheduler_run_task(**arguments)
        elif name == "scheduler_get_task_history":
            return await scheduler_tools.scheduler_get_task_history(**arguments)
        elif name == "scheduler_list_schedules":
            return await scheduler_tools.scheduler_list_schedules(**arguments)
        else:
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "error": "ToolNotFound",
                            "details": f"Tool '{name}' not found",
                        }
                    ),
                )
            ]
    except Exception as e:
        logger.exception(f"Error calling tool {name}")
        return [
            TextContent(
                type="text",
                text=json.dumps(
                    {
                        "error": "InternalError",
                        "details": str(e),
                    }
                ),
            )
        ]


async def _run_server() -> None:
    """Run the MCP server over stdio."""
    from mcp import stdio_server

    async with stdio_server() as (read_stream, write_stream):
        logger.info("Starting scheduler-mcp server")
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def main() -> None:
    """Entry point for the MCP server."""
    logger.setLevel(getattr(logging, settings.log_level.upper()))
    asyncio.run(_run_server())


if __name__ == "__main__":
    main()
