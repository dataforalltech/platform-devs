"""Analytics tools — 7 core tools for dashboards and metrics."""

import json
from typing import Any

import httpx

from src.config.settings import settings


async def list_dashboards(tenant_id: str) -> str:
    """List all dashboards for a tenant.

    Args:
        tenant_id: Tenant identifier

    Returns: JSON with dashboards list
    """
    try:
        async with httpx.AsyncClient(timeout=settings.MCP_ANALYTICS_TIMEOUT_SECONDS) as client:
            resp = await client.get(
                f"{settings.MCP_ANALYTICS_BASE_URL}/tenants/{tenant_id}/dashboards",
                headers={"Authorization": f"Bearer {settings.MCP_ANALYTICS_API_KEY}"},
                verify=settings.MCP_ANALYTICS_VERIFY_SSL,
            )
            if resp.status_code == 404:
                return json.dumps({"error": "NotFound", "details": f"Tenant {tenant_id} not found"})
            resp.raise_for_status()
            return json.dumps({"status": "ok", "data": resp.json()})
    except httpx.HTTPError as e:
        return json.dumps({"error": "HTTPError", "details": str(e)})
    except Exception as e:
        return json.dumps({"error": "Exception", "details": str(e)})


async def get_dashboard(dashboard_id: str) -> str:
    """Get dashboard details.

    Args:
        dashboard_id: Dashboard identifier

    Returns: JSON with dashboard data
    """
    try:
        async with httpx.AsyncClient(timeout=settings.MCP_ANALYTICS_TIMEOUT_SECONDS) as client:
            resp = await client.get(
                f"{settings.MCP_ANALYTICS_BASE_URL}/dashboards/{dashboard_id}",
                headers={"Authorization": f"Bearer {settings.MCP_ANALYTICS_API_KEY}"},
                verify=settings.MCP_ANALYTICS_VERIFY_SSL,
            )
            if resp.status_code == 404:
                return json.dumps({"error": "NotFound", "details": f"Dashboard {dashboard_id} not found"})
            resp.raise_for_status()
            return json.dumps({"status": "ok", "data": resp.json()})
    except httpx.HTTPError as e:
        return json.dumps({"error": "HTTPError", "details": str(e)})
    except Exception as e:
        return json.dumps({"error": "Exception", "details": str(e)})


async def create_dashboard(name: str, description: str, layout: dict[str, Any]) -> str:
    """Create a new dashboard.

    Args:
        name: Dashboard name
        description: Dashboard description
        layout: Dashboard layout configuration

    Returns: JSON with created dashboard
    """
    try:
        payload = {"name": name, "description": description, "layout": layout}
        async with httpx.AsyncClient(timeout=settings.MCP_ANALYTICS_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                f"{settings.MCP_ANALYTICS_BASE_URL}/dashboards",
                json=payload,
                headers={"Authorization": f"Bearer {settings.MCP_ANALYTICS_API_KEY}"},
                verify=settings.MCP_ANALYTICS_VERIFY_SSL,
            )
            if resp.status_code == 400:
                return json.dumps({"error": "BadRequest", "details": resp.text})
            resp.raise_for_status()
            return json.dumps({"status": "ok", "data": resp.json()})
    except httpx.HTTPError as e:
        return json.dumps({"error": "HTTPError", "details": str(e)})
    except Exception as e:
        return json.dumps({"error": "Exception", "details": str(e)})


async def refresh_dashboard(dashboard_id: str) -> str:
    """Refresh dashboard data.

    Args:
        dashboard_id: Dashboard identifier

    Returns: JSON with refresh result
    """
    try:
        async with httpx.AsyncClient(timeout=settings.MCP_ANALYTICS_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                f"{settings.MCP_ANALYTICS_BASE_URL}/dashboards/{dashboard_id}/refresh",
                json={},
                headers={"Authorization": f"Bearer {settings.MCP_ANALYTICS_API_KEY}"},
                verify=settings.MCP_ANALYTICS_VERIFY_SSL,
            )
            if resp.status_code == 404:
                return json.dumps({"error": "NotFound", "details": f"Dashboard {dashboard_id} not found"})
            resp.raise_for_status()
            return json.dumps({"status": "ok", "data": resp.json()})
    except httpx.HTTPError as e:
        return json.dumps({"error": "HTTPError", "details": str(e)})
    except Exception as e:
        return json.dumps({"error": "Exception", "details": str(e)})


async def get_metrics(dashboard_id: str, metric_name: str, time_range: str) -> str:
    """Get metrics data for a dashboard.

    Args:
        dashboard_id: Dashboard identifier
        metric_name: Metric name
        time_range: Time range (e.g., "24h", "7d", "30d")

    Returns: JSON with metrics data
    """
    try:
        async with httpx.AsyncClient(timeout=settings.MCP_ANALYTICS_TIMEOUT_SECONDS) as client:
            resp = await client.get(
                f"{settings.MCP_ANALYTICS_BASE_URL}/dashboards/{dashboard_id}/metrics/{metric_name}",
                params={"time_range": time_range},
                headers={"Authorization": f"Bearer {settings.MCP_ANALYTICS_API_KEY}"},
                verify=settings.MCP_ANALYTICS_VERIFY_SSL,
            )
            if resp.status_code == 404:
                return json.dumps({"error": "NotFound", "details": f"Dashboard {dashboard_id} not found"})
            resp.raise_for_status()
            return json.dumps({"status": "ok", "data": resp.json()})
    except httpx.HTTPError as e:
        return json.dumps({"error": "HTTPError", "details": str(e)})
    except Exception as e:
        return json.dumps({"error": "Exception", "details": str(e)})


async def query_data(sql: str, limit: int = 1000) -> str:
    """Execute analytics query.

    Args:
        sql: SQL query
        limit: Maximum rows to return

    Returns: JSON with query results
    """
    try:
        payload = {"sql": sql, "limit": limit}
        async with httpx.AsyncClient(timeout=settings.MCP_ANALYTICS_TIMEOUT_SECONDS * 2) as client:
            resp = await client.post(
                f"{settings.MCP_ANALYTICS_BASE_URL}/queries/execute",
                json=payload,
                headers={"Authorization": f"Bearer {settings.MCP_ANALYTICS_API_KEY}"},
                verify=settings.MCP_ANALYTICS_VERIFY_SSL,
            )
            if resp.status_code == 400:
                return json.dumps({"error": "BadRequest", "details": resp.text})
            resp.raise_for_status()
            return json.dumps({"status": "ok", "data": resp.json()})
    except httpx.HTTPError as e:
        return json.dumps({"error": "HTTPError", "details": str(e)})
    except Exception as e:
        return json.dumps({"error": "Exception", "details": str(e)})


async def export_dashboard(dashboard_id: str, format: str = "pdf") -> str:
    """Export dashboard to file.

    Args:
        dashboard_id: Dashboard identifier
        format: Export format (pdf, png, csv, json)

    Returns: JSON with export info and URL
    """
    try:
        payload = {"format": format}
        async with httpx.AsyncClient(timeout=settings.MCP_ANALYTICS_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                f"{settings.MCP_ANALYTICS_BASE_URL}/dashboards/{dashboard_id}/export",
                json=payload,
                headers={"Authorization": f"Bearer {settings.MCP_ANALYTICS_API_KEY}"},
                verify=settings.MCP_ANALYTICS_VERIFY_SSL,
            )
            if resp.status_code == 404:
                return json.dumps({"error": "NotFound", "details": f"Dashboard {dashboard_id} not found"})
            resp.raise_for_status()
            return json.dumps({"status": "ok", "data": resp.json()})
    except httpx.HTTPError as e:
        return json.dumps({"error": "HTTPError", "details": str(e)})
    except Exception as e:
        return json.dumps({"error": "Exception", "details": str(e)})
