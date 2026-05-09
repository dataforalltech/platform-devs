"""Analytics tools — dashboards, reports, and BI operations."""

import json
from typing import Any

import httpx

from src.config.settings import settings


async def analytics_list_dashboards() -> str:
    """List all dashboards."""
    try:
        async with httpx.AsyncClient(timeout=settings.MCP_ANALYTICS_TIMEOUT_SECONDS) as client:
            resp = await client.get(
                f"{settings.MCP_ANALYTICS_BASE_URL}/dashboards",
                headers={"Authorization": f"Bearer {settings.MCP_ANALYTICS_API_KEY}"},
            )
            resp.raise_for_status()
            return json.dumps({"status": "ok", "data": resp.json()})
    except Exception as e:
        return json.dumps({"error": "Exception", "details": str(e)})


async def analytics_get_dashboard(dashboard_id: str) -> str:
    """Get dashboard details and metadata."""
    try:
        async with httpx.AsyncClient(timeout=settings.MCP_ANALYTICS_TIMEOUT_SECONDS) as client:
            resp = await client.get(
                f"{settings.MCP_ANALYTICS_BASE_URL}/dashboards/{dashboard_id}",
                headers={"Authorization": f"Bearer {settings.MCP_ANALYTICS_API_KEY}"},
            )
            if resp.status_code == 404:
                return json.dumps({"error": "NotFound", "details": f"Dashboard {dashboard_id} not found"})
            resp.raise_for_status()
            return json.dumps({"status": "ok", "data": resp.json()})
    except Exception as e:
        return json.dumps({"error": "Exception", "details": str(e)})


async def analytics_create_report(name: str, query: str, dashboard_id: str | None = None) -> str:
    """Create new analytics report."""
    try:
        payload = {"name": name, "query": query, "dashboard_id": dashboard_id}
        async with httpx.AsyncClient(timeout=settings.MCP_ANALYTICS_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                f"{settings.MCP_ANALYTICS_BASE_URL}/reports",
                json=payload,
                headers={"Authorization": f"Bearer {settings.MCP_ANALYTICS_API_KEY}"},
            )
            resp.raise_for_status()
            return json.dumps({"status": "ok", "data": resp.json()})
    except Exception as e:
        return json.dumps({"error": "Exception", "details": str(e)})


async def analytics_execute_query(query: str) -> str:
    """Execute analytics query."""
    try:
        payload = {"query": query}
        async with httpx.AsyncClient(timeout=settings.MCP_ANALYTICS_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                f"{settings.MCP_ANALYTICS_BASE_URL}/queries/execute",
                json=payload,
                headers={"Authorization": f"Bearer {settings.MCP_ANALYTICS_API_KEY}"},
            )
            resp.raise_for_status()
            return json.dumps({"status": "ok", "data": resp.json()})
    except Exception as e:
        return json.dumps({"error": "Exception", "details": str(e)})


async def analytics_list_reports() -> str:
    """List all analytics reports."""
    try:
        async with httpx.AsyncClient(timeout=settings.MCP_ANALYTICS_TIMEOUT_SECONDS) as client:
            resp = await client.get(
                f"{settings.MCP_ANALYTICS_BASE_URL}/reports",
                headers={"Authorization": f"Bearer {settings.MCP_ANALYTICS_API_KEY}"},
            )
            resp.raise_for_status()
            return json.dumps({"status": "ok", "data": resp.json()})
    except Exception as e:
        return json.dumps({"error": "Exception", "details": str(e)})


async def analytics_get_report(report_id: str) -> str:
    """Get report details."""
    try:
        async with httpx.AsyncClient(timeout=settings.MCP_ANALYTICS_TIMEOUT_SECONDS) as client:
            resp = await client.get(
                f"{settings.MCP_ANALYTICS_BASE_URL}/reports/{report_id}",
                headers={"Authorization": f"Bearer {settings.MCP_ANALYTICS_API_KEY}"},
            )
            if resp.status_code == 404:
                return json.dumps({"error": "NotFound", "details": f"Report {report_id} not found"})
            resp.raise_for_status()
            return json.dumps({"status": "ok", "data": resp.json()})
    except Exception as e:
        return json.dumps({"error": "Exception", "details": str(e)})


async def analytics_delete_report(report_id: str) -> str:
    """Delete analytics report."""
    try:
        async with httpx.AsyncClient(timeout=settings.MCP_ANALYTICS_TIMEOUT_SECONDS) as client:
            resp = await client.delete(
                f"{settings.MCP_ANALYTICS_BASE_URL}/reports/{report_id}",
                headers={"Authorization": f"Bearer {settings.MCP_ANALYTICS_API_KEY}"},
            )
            if resp.status_code == 404:
                return json.dumps({"error": "NotFound", "details": f"Report {report_id} not found"})
            resp.raise_for_status()
            return json.dumps({"status": "ok", "data": resp.json()})
    except Exception as e:
        return json.dumps({"error": "Exception", "details": str(e)})
