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


async def monitor_get_metrics(service_name: str, metric_type: str = "cpu") -> str:
    """Get service metrics (cpu, memory, latency, etc.)."""
    try:
        async with httpx.AsyncClient(timeout=settings.MCP_MONITOR_TIMEOUT_SECONDS) as client:
            resp = await client.get(
                f"{settings.MCP_MONITOR_BASE_URL}/services/{service_name}/metrics",
                params={"type": metric_type},
                headers={"Authorization": f"Bearer {settings.MCP_MONITOR_API_KEY}"},
            )
            if resp.status_code == 404:
                return json.dumps({"error": "NotFound", "details": f"Service {service_name} not found"})
            resp.raise_for_status()
            return json.dumps({"status": "ok", "data": resp.json()})
    except Exception as e:
        return json.dumps({"error": "Exception", "details": str(e)})


async def monitor_list_alerts() -> str:
    """List all active alerts."""
    try:
        async with httpx.AsyncClient(timeout=settings.MCP_MONITOR_TIMEOUT_SECONDS) as client:
            resp = await client.get(
                f"{settings.MCP_MONITOR_BASE_URL}/alerts",
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
