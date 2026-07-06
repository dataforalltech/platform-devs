from mcp.types import TextContent

async def scheduler_health_check() -> list[TextContent]:
    return [TextContent(type="text", text='{"status": "ok"}')]

async def scheduler_list_jobs() -> list[TextContent]:
    return [TextContent(type="text", text='{"jobs": []}')]

async def scheduler_get_job(job_id: str) -> list[TextContent]:
    return [TextContent(type="text", text=f'{{"job_id": "{job_id}", "name": "N/A"}}')]

async def scheduler_create_job(name: str, schedule: str, handler: str) -> list[TextContent]:
    return [TextContent(type="text", text=f'{{"id": "new", "name": "{name}", "schedule": "{schedule}", "created": true}}')]

async def scheduler_update_job(job_id: str, **kwargs) -> list[TextContent]:
    return [TextContent(type="text", text=f'{{"job_id": "{job_id}", "updated": true}}')]

async def scheduler_delete_job(job_id: str) -> list[TextContent]:
    return [TextContent(type="text", text=f'{{"job_id": "{job_id}", "deleted": true}}')]

async def scheduler_trigger_job(job_id: str) -> list[TextContent]:
    return [TextContent(type="text", text=f'{{"job_id": "{job_id}", "triggered": true}}')]
