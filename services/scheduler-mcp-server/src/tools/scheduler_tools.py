"""Scheduler tools for platform-scheduler-mcp."""

import json
import logging
from typing import Any

from mcp.types import TextContent

from ..client.api_client import SchedulerApiClient
from ..config.settings import Settings

logger = logging.getLogger(__name__)

# Lazy singleton pattern for test monkeypatching
_settings: Settings | None = None
_api_client: SchedulerApiClient | None = None

# Module-level None sentinel for test monkeypatching
api_client: SchedulerApiClient | None = None
settings: Settings | None = None


def _get_settings() -> Settings:
    """Get or create settings singleton."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def _get_api_client() -> SchedulerApiClient:
    """Get or create API client singleton."""
    global _api_client
    if _api_client is None:
        _api_client = SchedulerApiClient(_get_settings())
    return _api_client


async def scheduler_health_check() -> list[TextContent]:
    """Check if platform-scheduler service is healthy.

    Returns:
        List containing status response as JSON.
    """
    client = api_client if api_client is not None else _get_api_client()
    try:
        response = await client.get("/api/health")
        if response.status_code == 200:
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "status": "ok",
                            "data": response.json(),
                        }
                    ),
                )
            ]
        else:
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "error": "HealthCheckFailed",
                            "details": f"Status {response.status_code}",
                        }
                    ),
                )
            ]
    except Exception as e:
        logger.exception("Error checking health")
        return [
            TextContent(
                type="text",
                text=json.dumps({"error": "InternalError", "details": str(e)}),
            )
        ]


async def scheduler_list_tasks(tenant_id: str | None = None) -> list[TextContent]:
    """List all scheduler tasks.

    Args:
        tenant_id: Optional tenant ID filter.

    Returns:
        List containing tasks information.
    """
    client = api_client if api_client is not None else _get_api_client()
    try:
        params = {}
        if tenant_id:
            params["tenant_id"] = tenant_id

        response = await client.get("/api/v1/tasks", params=params)
        if response.status_code == 200:
            return [TextContent(type="text", text=json.dumps(response.json()))]
        else:
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "error": "ListTasksFailed",
                            "details": f"Status {response.status_code}",
                        }
                    ),
                )
            ]
    except Exception as e:
        logger.exception("Error listing tasks")
        return [
            TextContent(
                type="text",
                text=json.dumps({"error": "InternalError", "details": str(e)}),
            )
        ]


async def scheduler_get_task(task_id: str) -> list[TextContent]:
    """Get details of a specific scheduler task.

    Args:
        task_id: The task ID.

    Returns:
        List containing task details.
    """
    client = api_client if api_client is not None else _get_api_client()
    try:
        response = await client.get(f"/api/v1/tasks/{task_id}")
        if response.status_code == 200:
            return [TextContent(type="text", text=json.dumps(response.json()))]
        elif response.status_code == 404:
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "error": "NotFound",
                            "details": f"Task {task_id} not found",
                        }
                    ),
                )
            ]
        else:
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "error": "GetTaskFailed",
                            "details": f"Status {response.status_code}",
                        }
                    ),
                )
            ]
    except Exception as e:
        logger.exception("Error getting task")
        return [
            TextContent(
                type="text",
                text=json.dumps({"error": "InternalError", "details": str(e)}),
            )
        ]


async def scheduler_create_task(
    cron_expression: str,
    command: str,
    tenant_id: str,
    name: str | None = None,
    description: str | None = None,
) -> list[TextContent]:
    """Create a new scheduler task.

    Args:
        cron_expression: Cron expression for task scheduling.
        command: Command to execute.
        tenant_id: Tenant ID for multi-tenancy.
        name: Optional task name.
        description: Optional task description.

    Returns:
        List containing created task details.
    """
    client = api_client if api_client is not None else _get_api_client()
    try:
        payload: dict[str, Any] = {
            "cron_expression": cron_expression,
            "command": command,
            "tenant_id": tenant_id,
        }
        if name:
            payload["name"] = name
        if description:
            payload["description"] = description

        response = await client.post("/api/v1/tasks", json=payload)
        if response.status_code == 201:
            return [TextContent(type="text", text=json.dumps(response.json()))]
        else:
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "error": "CreateTaskFailed",
                            "details": f"Status {response.status_code}",
                        }
                    ),
                )
            ]
    except Exception as e:
        logger.exception("Error creating task")
        return [
            TextContent(
                type="text",
                text=json.dumps({"error": "InternalError", "details": str(e)}),
            )
        ]


async def scheduler_update_task(
    task_id: str,
    cron_expression: str | None = None,
    command: str | None = None,
    name: str | None = None,
    description: str | None = None,
) -> list[TextContent]:
    """Update an existing scheduler task.

    Args:
        task_id: The task ID to update.
        cron_expression: Optional new cron expression.
        command: Optional new command.
        name: Optional new task name.
        description: Optional new task description.

    Returns:
        List containing updated task details.
    """
    client = api_client if api_client is not None else _get_api_client()
    try:
        payload: dict[str, Any] = {}
        if cron_expression is not None:
            payload["cron_expression"] = cron_expression
        if command is not None:
            payload["command"] = command
        if name is not None:
            payload["name"] = name
        if description is not None:
            payload["description"] = description

        response = await client.put(f"/api/v1/tasks/{task_id}", json=payload)
        if response.status_code == 200:
            return [TextContent(type="text", text=json.dumps(response.json()))]
        elif response.status_code == 404:
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "error": "NotFound",
                            "details": f"Task {task_id} not found",
                        }
                    ),
                )
            ]
        else:
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "error": "UpdateTaskFailed",
                            "details": f"Status {response.status_code}",
                        }
                    ),
                )
            ]
    except Exception as e:
        logger.exception("Error updating task")
        return [
            TextContent(
                type="text",
                text=json.dumps({"error": "InternalError", "details": str(e)}),
            )
        ]


async def scheduler_run_task(task_id: str) -> list[TextContent]:
    """Execute a task immediately.

    Args:
        task_id: The task ID to execute.

    Returns:
        List containing execution result.
    """
    client = api_client if api_client is not None else _get_api_client()
    try:
        response = await client.post(f"/api/v1/tasks/{task_id}/run", json={})
        if response.status_code == 200:
            return [TextContent(type="text", text=json.dumps(response.json()))]
        elif response.status_code == 404:
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "error": "NotFound",
                            "details": f"Task {task_id} not found",
                        }
                    ),
                )
            ]
        else:
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "error": "RunTaskFailed",
                            "details": f"Status {response.status_code}",
                        }
                    ),
                )
            ]
    except Exception as e:
        logger.exception("Error running task")
        return [
            TextContent(
                type="text",
                text=json.dumps({"error": "InternalError", "details": str(e)}),
            )
        ]


async def scheduler_get_task_history(task_id: str, limit: int = 10) -> list[TextContent]:
    """Get execution history of a task.

    Args:
        task_id: The task ID.
        limit: Maximum number of history records to return.

    Returns:
        List containing task execution history.
    """
    client = api_client if api_client is not None else _get_api_client()
    try:
        params = {"limit": limit}
        response = await client.get(f"/api/v1/tasks/{task_id}/history", params=params)
        if response.status_code == 200:
            return [TextContent(type="text", text=json.dumps(response.json()))]
        elif response.status_code == 404:
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "error": "NotFound",
                            "details": f"Task {task_id} not found",
                        }
                    ),
                )
            ]
        else:
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "error": "GetHistoryFailed",
                            "details": f"Status {response.status_code}",
                        }
                    ),
                )
            ]
    except Exception as e:
        logger.exception("Error getting task history")
        return [
            TextContent(
                type="text",
                text=json.dumps({"error": "InternalError", "details": str(e)}),
            )
        ]


async def scheduler_list_schedules(tenant_id: str | None = None) -> list[TextContent]:
    """List all active schedules.

    Args:
        tenant_id: Optional tenant ID filter.

    Returns:
        List containing schedules information.
    """
    client = api_client if api_client is not None else _get_api_client()
    try:
        params = {}
        if tenant_id:
            params["tenant_id"] = tenant_id

        response = await client.get("/api/v1/schedules", params=params)
        if response.status_code == 200:
            return [TextContent(type="text", text=json.dumps(response.json()))]
        else:
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "error": "ListSchedulesFailed",
                            "details": f"Status {response.status_code}",
                        }
                    ),
                )
            ]
    except Exception as e:
        logger.exception("Error listing schedules")
        return [
            TextContent(
                type="text",
                text=json.dumps({"error": "InternalError", "details": str(e)}),
            )
        ]
