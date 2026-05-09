"""Datalake tools — dataset operations, schema discovery, ML preparation."""

import json
from typing import Any

import httpx

from src.config.settings import settings


async def datalake_list_schemas() -> str:
    """List all available schemas in datalake.

    Returns: JSON with list of schemas
    """
    try:
        async with httpx.AsyncClient(timeout=settings.MCP_DATALAKE_TIMEOUT_SECONDS) as client:
            resp = await client.get(
                f"{settings.MCP_DATALAKE_BASE_URL}/schemas",
                headers={"Authorization": f"Bearer {settings.MCP_DATALAKE_API_KEY}"},
                verify=settings.MCP_DATALAKE_VERIFY_SSL,
            )
            resp.raise_for_status()
            return json.dumps({"status": "ok", "data": resp.json()})
    except httpx.HTTPError as e:
        return json.dumps({"error": "HTTPError", "details": str(e)})
    except Exception as e:
        return json.dumps({"error": "Exception", "details": str(e)})


async def datalake_get_schema(schema_name: str) -> str:
    """Get schema details including tables and columns.

    Args:
        schema_name: Name of the schema

    Returns: JSON with schema structure
    """
    try:
        async with httpx.AsyncClient(timeout=settings.MCP_DATALAKE_TIMEOUT_SECONDS) as client:
            resp = await client.get(
                f"{settings.MCP_DATALAKE_BASE_URL}/schemas/{schema_name}",
                headers={"Authorization": f"Bearer {settings.MCP_DATALAKE_API_KEY}"},
                verify=settings.MCP_DATALAKE_VERIFY_SSL,
            )
            if resp.status_code == 404:
                return json.dumps({"error": "NotFound", "details": f"Schema {schema_name} not found"})
            resp.raise_for_status()
            return json.dumps({"status": "ok", "data": resp.json()})
    except httpx.HTTPError as e:
        return json.dumps({"error": "HTTPError", "details": str(e)})
    except Exception as e:
        return json.dumps({"error": "Exception", "details": str(e)})


async def datalake_list_datasets() -> str:
    """List all available datasets in datalake.

    Returns: JSON with list of datasets
    """
    try:
        async with httpx.AsyncClient(timeout=settings.MCP_DATALAKE_TIMEOUT_SECONDS) as client:
            resp = await client.get(
                f"{settings.MCP_DATALAKE_BASE_URL}/datasets",
                headers={"Authorization": f"Bearer {settings.MCP_DATALAKE_API_KEY}"},
                verify=settings.MCP_DATALAKE_VERIFY_SSL,
            )
            resp.raise_for_status()
            return json.dumps({"status": "ok", "data": resp.json()})
    except httpx.HTTPError as e:
        return json.dumps({"error": "HTTPError", "details": str(e)})
    except Exception as e:
        return json.dumps({"error": "Exception", "details": str(e)})


async def datalake_get_dataset(dataset_id: str) -> str:
    """Get dataset details and metadata.

    Args:
        dataset_id: ID of the dataset

    Returns: JSON with dataset information
    """
    try:
        async with httpx.AsyncClient(timeout=settings.MCP_DATALAKE_TIMEOUT_SECONDS) as client:
            resp = await client.get(
                f"{settings.MCP_DATALAKE_BASE_URL}/datasets/{dataset_id}",
                headers={"Authorization": f"Bearer {settings.MCP_DATALAKE_API_KEY}"},
                verify=settings.MCP_DATALAKE_VERIFY_SSL,
            )
            if resp.status_code == 404:
                return json.dumps({"error": "NotFound", "details": f"Dataset {dataset_id} not found"})
            resp.raise_for_status()
            return json.dumps({"status": "ok", "data": resp.json()})
    except httpx.HTTPError as e:
        return json.dumps({"error": "HTTPError", "details": str(e)})
    except Exception as e:
        return json.dumps({"error": "Exception", "details": str(e)})


async def datalake_prepare_for_ml(dataset_id: str, model_type: str) -> str:
    """Prepare dataset for ML training (train/test split, normalization, feature engineering).

    Args:
        dataset_id: ID of the dataset
        model_type: Type of ML model (classification, regression, clustering)

    Returns: JSON with prepared dataset info
    """
    try:
        async with httpx.AsyncClient(timeout=settings.MCP_DATALAKE_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                f"{settings.MCP_DATALAKE_BASE_URL}/datasets/{dataset_id}/prepare-ml",
                json={"model_type": model_type},
                headers={"Authorization": f"Bearer {settings.MCP_DATALAKE_API_KEY}"},
                verify=settings.MCP_DATALAKE_VERIFY_SSL,
            )
            if resp.status_code == 404:
                return json.dumps({"error": "NotFound", "details": f"Dataset {dataset_id} not found"})
            resp.raise_for_status()
            return json.dumps({"status": "ok", "data": resp.json()})
    except httpx.HTTPError as e:
        return json.dumps({"error": "HTTPError", "details": str(e)})
    except Exception as e:
        return json.dumps({"error": "Exception", "details": str(e)})


async def datalake_sample_data(dataset_id: str, limit: int = 10) -> str:
    """Get sample of data from dataset.

    Args:
        dataset_id: ID of the dataset
        limit: Number of rows to return

    Returns: JSON with sample data
    """
    try:
        async with httpx.AsyncClient(timeout=settings.MCP_DATALAKE_TIMEOUT_SECONDS) as client:
            resp = await client.get(
                f"{settings.MCP_DATALAKE_BASE_URL}/datasets/{dataset_id}/sample",
                params={"limit": limit},
                headers={"Authorization": f"Bearer {settings.MCP_DATALAKE_API_KEY}"},
                verify=settings.MCP_DATALAKE_VERIFY_SSL,
            )
            if resp.status_code == 404:
                return json.dumps({"error": "NotFound", "details": f"Dataset {dataset_id} not found"})
            resp.raise_for_status()
            return json.dumps({"status": "ok", "data": resp.json()})
    except httpx.HTTPError as e:
        return json.dumps({"error": "HTTPError", "details": str(e)})
    except Exception as e:
        return json.dumps({"error": "Exception", "details": str(e)})


async def datalake_create_dataset(name: str, schema: dict[str, Any], description: str = "") -> str:
    """Create new dataset in datalake.

    Args:
        name: Dataset name
        schema: Dataset schema (column definitions)
        description: Optional description

    Returns: JSON with created dataset info
    """
    try:
        payload = {
            "name": name,
            "schema": schema,
            "description": description,
        }
        async with httpx.AsyncClient(timeout=settings.MCP_DATALAKE_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                f"{settings.MCP_DATALAKE_BASE_URL}/datasets",
                json=payload,
                headers={"Authorization": f"Bearer {settings.MCP_DATALAKE_API_KEY}"},
                verify=settings.MCP_DATALAKE_VERIFY_SSL,
            )
            if resp.status_code == 400:
                return json.dumps({"error": "BadRequest", "details": resp.text})
            resp.raise_for_status()
            return json.dumps({"status": "ok", "data": resp.json()})
    except httpx.HTTPError as e:
        return json.dumps({"error": "HTTPError", "details": str(e)})
    except Exception as e:
        return json.dumps({"error": "Exception", "details": str(e)})


async def datalake_compute_statistics(dataset_id: str) -> str:
    """Compute statistics for dataset (mean, std, percentiles, distribution).

    Args:
        dataset_id: ID of the dataset

    Returns: JSON with statistics
    """
    try:
        async with httpx.AsyncClient(timeout=settings.MCP_DATALAKE_TIMEOUT_SECONDS * 2) as client:
            resp = await client.get(
                f"{settings.MCP_DATALAKE_BASE_URL}/datasets/{dataset_id}/statistics",
                headers={"Authorization": f"Bearer {settings.MCP_DATALAKE_API_KEY}"},
                verify=settings.MCP_DATALAKE_VERIFY_SSL,
            )
            if resp.status_code == 404:
                return json.dumps({"error": "NotFound", "details": f"Dataset {dataset_id} not found"})
            resp.raise_for_status()
            return json.dumps({"status": "ok", "data": resp.json()})
    except httpx.HTTPError as e:
        return json.dumps({"error": "HTTPError", "details": str(e)})
    except Exception as e:
        return json.dumps({"error": "Exception", "details": str(e)})
