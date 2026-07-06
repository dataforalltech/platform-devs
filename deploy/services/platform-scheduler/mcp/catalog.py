"""Tool registry for the platform-scheduler MCP sidecar (named ``catalog`` to avoid the
existing ``tools/`` package). Each tool maps to one scheduler REST op under ``/api/v1``."""

from __future__ import annotations

from typing import Any

TOOLS: dict[str, dict[str, Any]] = {
    "list_task_families": {"description": "List task families (reference data).",
        "method": "GET", "path": "/api/v1/schedulers/references/task-families",
        "inputSchema": {"type": "object", "properties": {}}},
    "list_periodicities": {"description": "List supported periodicities.",
        "method": "GET", "path": "/api/v1/schedulers/references/periodicities",
        "inputSchema": {"type": "object", "properties": {}}},
    "list_sync_methods": {"description": "List sync methods.",
        "method": "GET", "path": "/api/v1/schedulers/references/sync-methods",
        "inputSchema": {"type": "object", "properties": {}}},
    "list_ml_algorithms": {"description": "List ML algorithms available to schedules.",
        "method": "GET", "path": "/api/v1/schedulers/ml/algorithms",
        "inputSchema": {"type": "object", "properties": {}}},
    "list_schedulers": {"description": "List schedules (paginated).",
        "method": "GET", "path": "/api/v1/schedulers",
        "inputSchema": {"type": "object", "properties": {"page": {"type": "integer"},
                        "page_size": {"type": "integer"}}}},
    "get_scheduler": {"description": "Get one schedule by id.",
        "method": "GET", "path": "/api/v1/schedulers/{scheduler_id}",
        "inputSchema": {"type": "object", "properties": {"scheduler_id": {"type": "string"}},
                        "required": ["scheduler_id"]}},
    "get_scheduler_tasks": {"description": "List a schedule's tasks.",
        "method": "GET", "path": "/api/v1/schedulers/{scheduler_id}/tasks",
        "inputSchema": {"type": "object", "properties": {"scheduler_id": {"type": "string"}},
                        "required": ["scheduler_id"]}},
    "get_scheduler_logs": {"description": "List a schedule's run logs.",
        "method": "GET", "path": "/api/v1/schedulers/{scheduler_id}/logs",
        "inputSchema": {"type": "object", "properties": {"scheduler_id": {"type": "string"}},
                        "required": ["scheduler_id"]}},
    "create_scheduler": {"description": "Create a schedule (write).",
        "method": "POST", "path": "/api/v1/schedulers",
        "inputSchema": {"type": "object", "properties": {"body": {"type": "object"}}}},
    "update_scheduler": {"description": "Update a schedule (write).",
        "method": "PATCH", "path": "/api/v1/schedulers/{scheduler_id}",
        "inputSchema": {"type": "object", "properties": {"scheduler_id": {"type": "string"},
                        "body": {"type": "object"}}, "required": ["scheduler_id"]}},
    "delete_scheduler": {"description": "Delete a schedule (write).",
        "method": "DELETE", "path": "/api/v1/schedulers/{scheduler_id}",
        "inputSchema": {"type": "object", "properties": {"scheduler_id": {"type": "string"}},
                        "required": ["scheduler_id"]}},
    "run_schedule": {"description": "Run a schedule ad-hoc (write).",
        "method": "POST", "path": "/api/v1/schedulers/run",
        "inputSchema": {"type": "object", "properties": {"body": {"type": "object"}}}},
    "execute_scheduler": {"description": "Execute a specific schedule now (write).",
        "method": "POST", "path": "/api/v1/schedulers/{scheduler_id}/execute",
        "inputSchema": {"type": "object", "properties": {"scheduler_id": {"type": "string"}},
                        "required": ["scheduler_id"]}},
    "list_recommendations": {"description": "List schedule recommendations.",
        "method": "GET", "path": "/api/v1/schedulers/recommendations",
        "inputSchema": {"type": "object", "properties": {}}},
    "get_task_general": {"description": "Get general info for a reference task.",
        "method": "GET", "path": "/api/v1/schedulers/references/tasks/{task_id}",
        "inputSchema": {"type": "object", "properties": {"task_id": {"type": "string"}}, "required": ["task_id"]}},
    "get_schedule_task_list": {"description": "List schedule tasks by family + origin.",
        "method": "GET", "path": "/api/v1/schedulers/by-family/{id_family}/origin/{id_origin}",
        "inputSchema": {"type": "object", "properties": {"id_family": {"type": "string"}, "id_origin": {"type": "string"}},
                        "required": ["id_family", "id_origin"]}},
    "get_list_task_by_family": {"description": "List tasks by family + parent.",
        "method": "GET", "path": "/api/v1/schedulers/list-task/{id_family}/{id_parent}",
        "inputSchema": {"type": "object", "properties": {"id_family": {"type": "string"}, "id_parent": {"type": "string"}},
                        "required": ["id_family", "id_parent"]}},
    "get_log_stages": {"description": "Get stages of a schedule run log.",
        "method": "GET", "path": "/api/v1/schedulers/{scheduler_id}/logs/{log_id}/stages",
        "inputSchema": {"type": "object", "properties": {"scheduler_id": {"type": "string"}, "log_id": {"type": "string"}},
                        "required": ["scheduler_id", "log_id"]}},
    "get_item_stages": {"description": "Get stages of a log item.",
        "method": "GET", "path": "/api/v1/schedulers/{scheduler_id}/logs/{log_id}/items/{item_id}/stages",
        "inputSchema": {"type": "object", "properties": {"scheduler_id": {"type": "string"}, "log_id": {"type": "string"},
                        "item_id": {"type": "string"}}, "required": ["scheduler_id", "log_id", "item_id"]}},
    "update_scheduler_inline": {"description": "Inline-update a schedule field (write).",
        "method": "PATCH", "path": "/api/v1/schedulers/{scheduler_id}/inline",
        "inputSchema": {"type": "object", "properties": {"scheduler_id": {"type": "string"}, "body": {"type": "object"}},
                        "required": ["scheduler_id"]}},
    "check_health": {"description": "Liveness probe (exempt from the PEP).",
        "method": "GET", "path": "/api/health/ready",
        "inputSchema": {"type": "object", "properties": {}}},
}


def resolve_path(path: str, args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    remaining = dict(args or {})
    out = path
    for key in list(remaining.keys()):
        ph = "{" + key + "}"
        if ph in out:
            out = out.replace(ph, str(remaining.pop(key)))
    return out, remaining
