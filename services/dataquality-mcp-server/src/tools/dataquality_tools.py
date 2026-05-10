"""Data quality tools — validation, anomaly detection, and rule management."""

import json
from typing import Any

import httpx

from src.config.settings import settings


async def dataquality_list_rules() -> str:
    """List all validation rules."""
    try:
        async with httpx.AsyncClient(timeout=settings.MCP_DATAQUALITY_TIMEOUT_SECONDS) as client:
            resp = await client.get(
                f"{settings.MCP_DATAQUALITY_BASE_URL}/rules",
                headers={"Authorization": f"Bearer {settings.MCP_DATAQUALITY_API_KEY}"},
            )
            resp.raise_for_status()
            return json.dumps({"status": "ok", "data": resp.json()})
    except Exception as e:
        return json.dumps({"error": "Exception", "details": str(e)})


async def dataquality_create_rule(dataset_id: str, rule_name: str, rule_type: str, config: dict[str, Any]) -> str:
    """Create new validation rule."""
    try:
        payload = {"dataset_id": dataset_id, "rule_name": rule_name, "rule_type": rule_type, "config": config}
        async with httpx.AsyncClient(timeout=settings.MCP_DATAQUALITY_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                f"{settings.MCP_DATAQUALITY_BASE_URL}/rules",
                json=payload,
                headers={"Authorization": f"Bearer {settings.MCP_DATAQUALITY_API_KEY}"},
            )
            resp.raise_for_status()
            return json.dumps({"status": "ok", "data": resp.json()})
    except Exception as e:
        return json.dumps({"error": "Exception", "details": str(e)})


async def dataquality_run_validation(dataset_id: str, rule_ids: list[str] | None = None) -> str:
    """Execute validation against dataset."""
    try:
        payload = {"rule_ids": rule_ids or []}
        async with httpx.AsyncClient(timeout=settings.MCP_DATAQUALITY_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                f"{settings.MCP_DATAQUALITY_BASE_URL}/datasets/{dataset_id}/validate",
                json=payload,
                headers={"Authorization": f"Bearer {settings.MCP_DATAQUALITY_API_KEY}"},
            )
            if resp.status_code == 404:
                return json.dumps({"error": "NotFound", "details": f"Dataset {dataset_id} not found"})
            resp.raise_for_status()
            return json.dumps({"status": "ok", "data": resp.json()})
    except Exception as e:
        return json.dumps({"error": "Exception", "details": str(e)})


async def dataquality_get_anomalies(dataset_id: str, anomaly_type: str | None = None, limit: int = 100) -> str:
    """Detect and list data anomalies."""
    try:
        params = {"limit": limit}
        if anomaly_type:
            params["anomaly_type"] = anomaly_type
        async with httpx.AsyncClient(timeout=settings.MCP_DATAQUALITY_TIMEOUT_SECONDS) as client:
            resp = await client.get(
                f"{settings.MCP_DATAQUALITY_BASE_URL}/datasets/{dataset_id}/anomalies",
                params=params,
                headers={"Authorization": f"Bearer {settings.MCP_DATAQUALITY_API_KEY}"},
            )
            if resp.status_code == 404:
                return json.dumps({"error": "NotFound", "details": f"Dataset {dataset_id} not found"})
            resp.raise_for_status()
            return json.dumps({"status": "ok", "data": resp.json()})
    except Exception as e:
        return json.dumps({"error": "Exception", "details": str(e)})


async def dataquality_get_metrics(dataset_id: str, metric_type: str | None = None) -> str:
    """Get quality metrics and statistics for dataset."""
    try:
        params = {}
        if metric_type:
            params["metric_type"] = metric_type
        async with httpx.AsyncClient(timeout=settings.MCP_DATAQUALITY_TIMEOUT_SECONDS) as client:
            resp = await client.get(
                f"{settings.MCP_DATAQUALITY_BASE_URL}/datasets/{dataset_id}/metrics",
                params=params,
                headers={"Authorization": f"Bearer {settings.MCP_DATAQUALITY_API_KEY}"},
            )
            if resp.status_code == 404:
                return json.dumps({"error": "NotFound", "details": f"Dataset {dataset_id} not found"})
            resp.raise_for_status()
            return json.dumps({"status": "ok", "data": resp.json()})
    except Exception as e:
        return json.dumps({"error": "Exception", "details": str(e)})


async def dataquality_validate_dataset(dataset_id: str, include_anomalies: bool = False) -> str:
    """Perform full dataset validation including rules and anomalies."""
    try:
        payload = {"include_anomalies": include_anomalies}
        async with httpx.AsyncClient(timeout=settings.MCP_DATAQUALITY_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                f"{settings.MCP_DATAQUALITY_BASE_URL}/datasets/{dataset_id}/full-validate",
                json=payload,
                headers={"Authorization": f"Bearer {settings.MCP_DATAQUALITY_API_KEY}"},
            )
            if resp.status_code == 404:
                return json.dumps({"error": "NotFound", "details": f"Dataset {dataset_id} not found"})
            resp.raise_for_status()
            return json.dumps({"status": "ok", "data": resp.json()})
    except Exception as e:
        return json.dumps({"error": "Exception", "details": str(e)})


async def dataquality_get_rule(rule_id: str) -> str:
    """Get validation rule details."""
    try:
        async with httpx.AsyncClient(timeout=settings.MCP_DATAQUALITY_TIMEOUT_SECONDS) as client:
            resp = await client.get(
                f"{settings.MCP_DATAQUALITY_BASE_URL}/rules/{rule_id}",
                headers={"Authorization": f"Bearer {settings.MCP_DATAQUALITY_API_KEY}"},
            )
            if resp.status_code == 404:
                return json.dumps({"error": "NotFound", "details": f"Rule {rule_id} not found"})
            resp.raise_for_status()
            return json.dumps({"status": "ok", "data": resp.json()})
    except Exception as e:
        return json.dumps({"error": "Exception", "details": str(e)})


async def dataquality_delete_rule(rule_id: str) -> str:
    """Delete validation rule."""
    try:
        async with httpx.AsyncClient(timeout=settings.MCP_DATAQUALITY_TIMEOUT_SECONDS) as client:
            resp = await client.delete(
                f"{settings.MCP_DATAQUALITY_BASE_URL}/rules/{rule_id}",
                headers={"Authorization": f"Bearer {settings.MCP_DATAQUALITY_API_KEY}"},
            )
            if resp.status_code == 404:
                return json.dumps({"error": "NotFound", "details": f"Rule {rule_id} not found"})
            resp.raise_for_status()
            return json.dumps({"status": "ok", "data": resp.json()})
    except Exception as e:
        return json.dumps({"error": "Exception", "details": str(e)})


async def dataquality_get_validation_history(dataset_id: str, limit: int = 50) -> str:
    """Get validation history for a dataset."""
    try:
        params = {"limit": limit}
        async with httpx.AsyncClient(timeout=settings.MCP_DATAQUALITY_TIMEOUT_SECONDS) as client:
            resp = await client.get(
                f"{settings.MCP_DATAQUALITY_BASE_URL}/datasets/{dataset_id}/validation-history",
                params=params,
                headers={"Authorization": f"Bearer {settings.MCP_DATAQUALITY_API_KEY}"},
            )
            if resp.status_code == 404:
                return json.dumps({"error": "NotFound", "details": f"Dataset {dataset_id} not found"})
            resp.raise_for_status()
            return json.dumps({"status": "ok", "data": resp.json()})
    except Exception as e:
        return json.dumps({"error": "Exception", "details": str(e)})


async def dataquality_get_data_profile(dataset_id: str, columns: list[str] | None = None) -> str:
    """Get data profile with distributions, outliers, and missing percentages."""
    try:
        payload = {"columns": columns or []}
        async with httpx.AsyncClient(timeout=settings.MCP_DATAQUALITY_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                f"{settings.MCP_DATAQUALITY_BASE_URL}/datasets/{dataset_id}/profile",
                json=payload,
                headers={"Authorization": f"Bearer {settings.MCP_DATAQUALITY_API_KEY}"},
            )
            if resp.status_code == 404:
                return json.dumps({"error": "NotFound", "details": f"Dataset {dataset_id} not found"})
            resp.raise_for_status()
            return json.dumps({"status": "ok", "data": resp.json()})
    except Exception as e:
        return json.dumps({"error": "Exception", "details": str(e)})


async def dataquality_export_report(dataset_id: str, format: str = "pdf") -> str:
    """Export data quality report in specified format (pdf, csv, json)."""
    try:
        params = {"format": format}
        async with httpx.AsyncClient(timeout=settings.MCP_DATAQUALITY_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                f"{settings.MCP_DATAQUALITY_BASE_URL}/datasets/{dataset_id}/export-report",
                params=params,
                headers={"Authorization": f"Bearer {settings.MCP_DATAQUALITY_API_KEY}"},
            )
            if resp.status_code == 404:
                return json.dumps({"error": "NotFound", "details": f"Dataset {dataset_id} not found"})
            resp.raise_for_status()
            return json.dumps({"status": "ok", "data": resp.json()})
    except Exception as e:
        return json.dumps({"error": "Exception", "details": str(e)})


async def dataquality_health_check() -> str:
    """Check if platform-dataquality service is healthy."""
    try:
        async with httpx.AsyncClient(timeout=settings.MCP_DATAQUALITY_TIMEOUT_SECONDS) as client:
            resp = await client.get(
                f"{settings.MCP_DATAQUALITY_BASE_URL}/health",
                headers={"Authorization": f"Bearer {settings.MCP_DATAQUALITY_API_KEY}"},
            )
            resp.raise_for_status()
            return json.dumps({"status": "ok", "data": resp.json()})
    except Exception as e:
        return json.dumps({"error": "Exception", "details": str(e)})
