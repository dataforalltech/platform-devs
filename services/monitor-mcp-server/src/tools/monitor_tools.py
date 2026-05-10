"""Monitor tools — service monitoring, alerts, and health checks."""

import json
from typing import Any

import httpx

from src.config.settings import settings


async def monitor_get_service_status(service_name: str) -> str:
    """Get service health status."""
    try:
        async with httpx.AsyncClient(timeout=settings.MCP_MONITOR_TIMEOUT_SECONDS) as client:
            resp = await client.get(
                f"{settings.MCP_MONITOR_BASE_URL}/services/{service_name}/status",
                headers={"Authorization": f"Bearer {settings.MCP_MONITOR_API_KEY}"},
            )
            if resp.status_code == 404:
                return json.dumps({"error": "NotFound", "details": f"Service {service_name} not found"})
            resp.raise_for_status()
            return json.dumps({"status": "ok", "data": resp.json()})
    except Exception as e:
        return json.dumps({"error": "Exception", "details": str(e)})


async def monitor_list_services() -> str:
    """List all monitored services."""
    try:
        async with httpx.AsyncClient(timeout=settings.MCP_MONITOR_TIMEOUT_SECONDS) as client:
            resp = await client.get(
                f"{settings.MCP_MONITOR_BASE_URL}/services",
                headers={"Authorization": f"Bearer {settings.MCP_MONITOR_API_KEY}"},
            )
            resp.raise_for_status()
            return json.dumps({"status": "ok", "data": resp.json()})
    except Exception as e:
        return json.dumps({"error": "Exception", "details": str(e)})


async def monitor_get_metrics(service_name: str, metric_type: str = "cpu", time_range: str = "1h") -> str:
    """Get service metrics (cpu %, memory %, disk %, network Mbps)."""
    try:
        params = {"type": metric_type, "time_range": time_range}
        async with httpx.AsyncClient(timeout=settings.MCP_MONITOR_TIMEOUT_SECONDS) as client:
            resp = await client.get(
                f"{settings.MCP_MONITOR_BASE_URL}/services/{service_name}/metrics",
                params=params,
                headers={"Authorization": f"Bearer {settings.MCP_MONITOR_API_KEY}"},
            )
            if resp.status_code == 404:
                return json.dumps({"error": "NotFound", "details": f"Service {service_name} not found"})
            resp.raise_for_status()
            return json.dumps({"status": "ok", "data": resp.json()})
    except Exception as e:
        return json.dumps({"error": "Exception", "details": str(e)})


async def monitor_get_health_status(service_name: str) -> str:
    """Get service health status with uptime and response time."""
    try:
        async with httpx.AsyncClient(timeout=settings.MCP_MONITOR_TIMEOUT_SECONDS) as client:
            resp = await client.get(
                f"{settings.MCP_MONITOR_BASE_URL}/services/{service_name}/health",
                headers={"Authorization": f"Bearer {settings.MCP_MONITOR_API_KEY}"},
            )
            if resp.status_code == 404:
                return json.dumps({"error": "NotFound", "details": f"Service {service_name} not found"})
            resp.raise_for_status()
            return json.dumps({"status": "ok", "data": resp.json()})
    except Exception as e:
        return json.dumps({"error": "Exception", "details": str(e)})


async def monitor_list_alerts(service_name: str | None = None, severity: str | None = None) -> str:
    """List alerts with optional filters by service and severity."""
    try:
        params = {}
        if service_name:
            params["service_name"] = service_name
        if severity:
            params["severity"] = severity
        async with httpx.AsyncClient(timeout=settings.MCP_MONITOR_TIMEOUT_SECONDS) as client:
            resp = await client.get(
                f"{settings.MCP_MONITOR_BASE_URL}/alerts",
                params=params,
                headers={"Authorization": f"Bearer {settings.MCP_MONITOR_API_KEY}"},
            )
            resp.raise_for_status()
            return json.dumps({"status": "ok", "data": resp.json()})
    except Exception as e:
        return json.dumps({"error": "Exception", "details": str(e)})


async def monitor_get_alert(alert_id: str) -> str:
    """Get alert details."""
    try:
        async with httpx.AsyncClient(timeout=settings.MCP_MONITOR_TIMEOUT_SECONDS) as client:
            resp = await client.get(
                f"{settings.MCP_MONITOR_BASE_URL}/alerts/{alert_id}",
                headers={"Authorization": f"Bearer {settings.MCP_MONITOR_API_KEY}"},
            )
            if resp.status_code == 404:
                return json.dumps({"error": "NotFound", "details": f"Alert {alert_id} not found"})
            resp.raise_for_status()
            return json.dumps({"status": "ok", "data": resp.json()})
    except Exception as e:
        return json.dumps({"error": "Exception", "details": str(e)})


async def monitor_acknowledge_alert(alert_id: str) -> str:
    """Acknowledge alert."""
    try:
        async with httpx.AsyncClient(timeout=settings.MCP_MONITOR_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                f"{settings.MCP_MONITOR_BASE_URL}/alerts/{alert_id}/acknowledge",
                headers={"Authorization": f"Bearer {settings.MCP_MONITOR_API_KEY}"},
            )
            if resp.status_code == 404:
                return json.dumps({"error": "NotFound", "details": f"Alert {alert_id} not found"})
            resp.raise_for_status()
            return json.dumps({"status": "ok", "data": resp.json()})
    except Exception as e:
        return json.dumps({"error": "Exception", "details": str(e)})


async def monitor_create_alert_rule(service_name: str, condition: str, threshold: float) -> str:
    """Create new alert rule."""
    try:
        payload = {"service_name": service_name, "condition": condition, "threshold": threshold}
        async with httpx.AsyncClient(timeout=settings.MCP_MONITOR_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                f"{settings.MCP_MONITOR_BASE_URL}/alert-rules",
                json=payload,
                headers={"Authorization": f"Bearer {settings.MCP_MONITOR_API_KEY}"},
            )
            resp.raise_for_status()
            return json.dumps({"status": "ok", "data": resp.json()})
    except Exception as e:
        return json.dumps({"error": "Exception", "details": str(e)})


async def monitor_get_service_logs(service_name: str, level: str = "info", limit: int = 100) -> str:
    """Get service logs filtered by level."""
    try:
        params = {"level": level, "limit": limit}
        async with httpx.AsyncClient(timeout=settings.MCP_MONITOR_TIMEOUT_SECONDS) as client:
            resp = await client.get(
                f"{settings.MCP_MONITOR_BASE_URL}/services/{service_name}/logs",
                params=params,
                headers={"Authorization": f"Bearer {settings.MCP_MONITOR_API_KEY}"},
            )
            if resp.status_code == 404:
                return json.dumps({"error": "NotFound", "details": f"Service {service_name} not found"})
            resp.raise_for_status()
            return json.dumps({"status": "ok", "data": resp.json()})
    except Exception as e:
        return json.dumps({"error": "Exception", "details": str(e)})


async def monitor_get_performance_report(service_name: str, time_range: str = "24h") -> str:
    """Get comprehensive performance report with trends and anomalies."""
    try:
        params = {"time_range": time_range}
        async with httpx.AsyncClient(timeout=settings.MCP_MONITOR_TIMEOUT_SECONDS) as client:
            resp = await client.get(
                f"{settings.MCP_MONITOR_BASE_URL}/services/{service_name}/performance-report",
                params=params,
                headers={"Authorization": f"Bearer {settings.MCP_MONITOR_API_KEY}"},
            )
            if resp.status_code == 404:
                return json.dumps({"error": "NotFound", "details": f"Service {service_name} not found"})
            resp.raise_for_status()
            return json.dumps({"status": "ok", "data": resp.json()})
    except Exception as e:
        return json.dumps({"error": "Exception", "details": str(e)})
