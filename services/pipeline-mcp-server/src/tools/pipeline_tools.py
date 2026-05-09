"""Pipeline tools — orchestration, execution, monitoring."""

import json
from typing import Any

import httpx

from src.config.settings import settings


async def pipeline_create_pipeline(name: str, config: dict[str, Any]) -> str:
    """Create new pipeline."""
    try:
        payload = {"name": name, "config": config}
        async with httpx.AsyncClient(timeout=settings.MCP_PIPELINE_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                f"{settings.MCP_PIPELINE_BASE_URL}/pipelines",
                json=payload,
                headers={"Authorization": f"Bearer {settings.MCP_PIPELINE_API_KEY}"},
            )
            resp.raise_for_status()
            return json.dumps({"status": "ok", "data": resp.json()})
    except Exception as e:
        return json.dumps({"error": "Exception", "details": str(e)})


async def pipeline_get_pipeline(pipeline_id: str) -> str:
    """Get pipeline details."""
    try:
        async with httpx.AsyncClient(timeout=settings.MCP_PIPELINE_TIMEOUT_SECONDS) as client:
            resp = await client.get(
                f"{settings.MCP_PIPELINE_BASE_URL}/pipelines/{pipeline_id}",
                headers={"Authorization": f"Bearer {settings.MCP_PIPELINE_API_KEY}"},
            )
            if resp.status_code == 404:
                return json.dumps({"error": "NotFound", "details": f"Pipeline {pipeline_id} not found"})
            resp.raise_for_status()
            return json.dumps({"status": "ok", "data": resp.json()})
    except Exception as e:
        return json.dumps({"error": "Exception", "details": str(e)})


async def pipeline_list_pipelines() -> str:
    """List all pipelines."""
    try:
        async with httpx.AsyncClient(timeout=settings.MCP_PIPELINE_TIMEOUT_SECONDS) as client:
            resp = await client.get(
                f"{settings.MCP_PIPELINE_BASE_URL}/pipelines",
                headers={"Authorization": f"Bearer {settings.MCP_PIPELINE_API_KEY}"},
            )
            resp.raise_for_status()
            return json.dumps({"status": "ok", "data": resp.json()})
    except Exception as e:
        return json.dumps({"error": "Exception", "details": str(e)})


async def pipeline_trigger_run(pipeline_id: str, inputs: dict[str, Any] | None = None) -> str:
    """Trigger pipeline execution."""
    try:
        payload = {"inputs": inputs or {}}
        async with httpx.AsyncClient(timeout=settings.MCP_PIPELINE_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                f"{settings.MCP_PIPELINE_BASE_URL}/pipelines/{pipeline_id}/run",
                json=payload,
                headers={"Authorization": f"Bearer {settings.MCP_PIPELINE_API_KEY}"},
            )
            if resp.status_code == 404:
                return json.dumps({"error": "NotFound", "details": f"Pipeline {pipeline_id} not found"})
            resp.raise_for_status()
            return json.dumps({"status": "ok", "data": resp.json()})
    except Exception as e:
        return json.dumps({"error": "Exception", "details": str(e)})


async def pipeline_get_run_status(run_id: str) -> str:
    """Get pipeline run status."""
    try:
        async with httpx.AsyncClient(timeout=settings.MCP_PIPELINE_TIMEOUT_SECONDS) as client:
            resp = await client.get(
                f"{settings.MCP_PIPELINE_BASE_URL}/runs/{run_id}",
                headers={"Authorization": f"Bearer {settings.MCP_PIPELINE_API_KEY}"},
            )
            if resp.status_code == 404:
                return json.dumps({"error": "NotFound", "details": f"Run {run_id} not found"})
            resp.raise_for_status()
            return json.dumps({"status": "ok", "data": resp.json()})
    except Exception as e:
        return json.dumps({"error": "Exception", "details": str(e)})


async def pipeline_get_pipeline_logs(pipeline_id: str, run_id: str | None = None) -> str:
    """Get pipeline execution logs."""
    try:
        url = f"{settings.MCP_PIPELINE_BASE_URL}/pipelines/{pipeline_id}/logs"
        params = {"run_id": run_id} if run_id else {}
        async with httpx.AsyncClient(timeout=settings.MCP_PIPELINE_TIMEOUT_SECONDS) as client:
            resp = await client.get(
                url,
                params=params,
                headers={"Authorization": f"Bearer {settings.MCP_PIPELINE_API_KEY}"},
            )
            if resp.status_code == 404:
                return json.dumps({"error": "NotFound", "details": f"Pipeline {pipeline_id} not found"})
            resp.raise_for_status()
            return json.dumps({"status": "ok", "data": resp.json()})
    except Exception as e:
        return json.dumps({"error": "Exception", "details": str(e)})


async def pipeline_cancel_run(run_id: str) -> str:
    """Cancel pipeline run."""
    try:
        async with httpx.AsyncClient(timeout=settings.MCP_PIPELINE_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                f"{settings.MCP_PIPELINE_BASE_URL}/runs/{run_id}/cancel",
                headers={"Authorization": f"Bearer {settings.MCP_PIPELINE_API_KEY}"},
            )
            if resp.status_code == 404:
                return json.dumps({"error": "NotFound", "details": f"Run {run_id} not found"})
            resp.raise_for_status()
            return json.dumps({"status": "ok", "data": resp.json()})
    except Exception as e:
        return json.dumps({"error": "Exception", "details": str(e)})


async def pipeline_delete_pipeline(pipeline_id: str) -> str:
    """Delete pipeline."""
    try:
        async with httpx.AsyncClient(timeout=settings.MCP_PIPELINE_TIMEOUT_SECONDS) as client:
            resp = await client.delete(
                f"{settings.MCP_PIPELINE_BASE_URL}/pipelines/{pipeline_id}",
                headers={"Authorization": f"Bearer {settings.MCP_PIPELINE_API_KEY}"},
            )
            if resp.status_code == 404:
                return json.dumps({"error": "NotFound", "details": f"Pipeline {pipeline_id} not found"})
            resp.raise_for_status()
            return json.dumps({"status": "ok", "data": resp.json()})
    except Exception as e:
        return json.dumps({"error": "Exception", "details": str(e)})


async def pipeline_get_run_history(pipeline_id: str, limit: int = 20) -> str:
    """Get execution history for pipeline."""
    try:
        async with httpx.AsyncClient(timeout=settings.MCP_PIPELINE_TIMEOUT_SECONDS) as client:
            resp = await client.get(
                f"{settings.MCP_PIPELINE_BASE_URL}/pipelines/{pipeline_id}/history",
                params={"limit": limit},
                headers={"Authorization": f"Bearer {settings.MCP_PIPELINE_API_KEY}"},
            )
            if resp.status_code == 404:
                return json.dumps({"error": "NotFound", "details": f"Pipeline {pipeline_id} not found"})
            resp.raise_for_status()
            return json.dumps({"status": "ok", "data": resp.json()})
    except Exception as e:
        return json.dumps({"error": "Exception", "details": str(e)})
