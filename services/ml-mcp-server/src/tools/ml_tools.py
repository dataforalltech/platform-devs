"""ML tools — 9 core tools for model management, training, and inference."""

import json
from typing import Any

import httpx

from src.config.settings import settings


async def list_models(tenant_id: str) -> str:
    """List all models for a tenant.

    Args:
        tenant_id: Tenant identifier

    Returns: JSON with list of models
    """
    try:
        async with httpx.AsyncClient(timeout=settings.MCP_ML_TIMEOUT_SECONDS) as client:
            resp = await client.get(
                f"{settings.MCP_ML_BASE_URL}/tenants/{tenant_id}/models",
                headers={"Authorization": f"Bearer {settings.MCP_ML_API_KEY}"},
                verify=settings.MCP_ML_VERIFY_SSL,
            )
            if resp.status_code == 404:
                return json.dumps({"error": "NotFound", "details": f"Tenant {tenant_id} not found"})
            resp.raise_for_status()
            return json.dumps({"status": "ok", "data": resp.json()})
    except httpx.HTTPError as e:
        return json.dumps({"error": "HTTPError", "details": str(e)})
    except Exception as e:
        return json.dumps({"error": "Exception", "details": str(e)})


async def get_model(model_id: str) -> str:
    """Get model details.

    Args:
        model_id: Model identifier

    Returns: JSON with model metadata
    """
    try:
        async with httpx.AsyncClient(timeout=settings.MCP_ML_TIMEOUT_SECONDS) as client:
            resp = await client.get(
                f"{settings.MCP_ML_BASE_URL}/models/{model_id}",
                headers={"Authorization": f"Bearer {settings.MCP_ML_API_KEY}"},
                verify=settings.MCP_ML_VERIFY_SSL,
            )
            if resp.status_code == 404:
                return json.dumps({"error": "NotFound", "details": f"Model {model_id} not found"})
            resp.raise_for_status()
            return json.dumps({"status": "ok", "data": resp.json()})
    except httpx.HTTPError as e:
        return json.dumps({"error": "HTTPError", "details": str(e)})
    except Exception as e:
        return json.dumps({"error": "Exception", "details": str(e)})


async def create_model(name: str, type: str, config: dict[str, Any]) -> str:
    """Create a new model definition.

    Args:
        name: Model name
        type: Model type (classification, regression, clustering)
        config: Model configuration

    Returns: JSON with created model
    """
    try:
        payload = {"name": name, "type": type, "config": config}
        async with httpx.AsyncClient(timeout=settings.MCP_ML_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                f"{settings.MCP_ML_BASE_URL}/models",
                json=payload,
                headers={"Authorization": f"Bearer {settings.MCP_ML_API_KEY}"},
                verify=settings.MCP_ML_VERIFY_SSL,
            )
            if resp.status_code == 400:
                return json.dumps({"error": "BadRequest", "details": resp.text})
            resp.raise_for_status()
            return json.dumps({"status": "ok", "data": resp.json()})
    except httpx.HTTPError as e:
        return json.dumps({"error": "HTTPError", "details": str(e)})
    except Exception as e:
        return json.dumps({"error": "Exception", "details": str(e)})


async def train_model(model_id: str, dataset_id: str, hyperparams: dict[str, Any] | None = None) -> str:
    """Train a model.

    Args:
        model_id: Model identifier
        dataset_id: Dataset identifier
        hyperparams: Optional hyperparameters

    Returns: JSON with job info
    """
    try:
        payload = {"dataset_id": dataset_id, "hyperparams": hyperparams or {}}
        async with httpx.AsyncClient(timeout=settings.MCP_ML_TIMEOUT_SECONDS * 2) as client:
            resp = await client.post(
                f"{settings.MCP_ML_BASE_URL}/models/{model_id}/train",
                json=payload,
                headers={"Authorization": f"Bearer {settings.MCP_ML_API_KEY}"},
                verify=settings.MCP_ML_VERIFY_SSL,
            )
            if resp.status_code == 404:
                return json.dumps({"error": "NotFound", "details": f"Model {model_id} not found"})
            resp.raise_for_status()
            return json.dumps({"status": "ok", "data": resp.json()})
    except httpx.HTTPError as e:
        return json.dumps({"error": "HTTPError", "details": str(e)})
    except Exception as e:
        return json.dumps({"error": "Exception", "details": str(e)})


async def get_training_status(job_id: str) -> str:
    """Get status of a training job.

    Args:
        job_id: Job identifier

    Returns: JSON with job status
    """
    try:
        async with httpx.AsyncClient(timeout=settings.MCP_ML_TIMEOUT_SECONDS) as client:
            resp = await client.get(
                f"{settings.MCP_ML_BASE_URL}/jobs/{job_id}",
                headers={"Authorization": f"Bearer {settings.MCP_ML_API_KEY}"},
                verify=settings.MCP_ML_VERIFY_SSL,
            )
            if resp.status_code == 404:
                return json.dumps({"error": "NotFound", "details": f"Job {job_id} not found"})
            resp.raise_for_status()
            return json.dumps({"status": "ok", "data": resp.json()})
    except httpx.HTTPError as e:
        return json.dumps({"error": "HTTPError", "details": str(e)})
    except Exception as e:
        return json.dumps({"error": "Exception", "details": str(e)})


async def evaluate_model(model_id: str, test_dataset_id: str) -> str:
    """Evaluate model on test dataset.

    Args:
        model_id: Model identifier
        test_dataset_id: Test dataset identifier

    Returns: JSON with metrics
    """
    try:
        payload = {"test_dataset_id": test_dataset_id}
        async with httpx.AsyncClient(timeout=settings.MCP_ML_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                f"{settings.MCP_ML_BASE_URL}/models/{model_id}/evaluate",
                json=payload,
                headers={"Authorization": f"Bearer {settings.MCP_ML_API_KEY}"},
                verify=settings.MCP_ML_VERIFY_SSL,
            )
            if resp.status_code == 404:
                return json.dumps({"error": "NotFound", "details": f"Model {model_id} not found"})
            resp.raise_for_status()
            return json.dumps({"status": "ok", "data": resp.json()})
    except httpx.HTTPError as e:
        return json.dumps({"error": "HTTPError", "details": str(e)})
    except Exception as e:
        return json.dumps({"error": "Exception", "details": str(e)})


async def deploy_model(model_id: str, version: str, environment: str) -> str:
    """Deploy model to environment.

    Args:
        model_id: Model identifier
        version: Model version
        environment: Target environment (dev, staging, prod)

    Returns: JSON with deployment info
    """
    try:
        payload = {"version": version, "environment": environment}
        async with httpx.AsyncClient(timeout=settings.MCP_ML_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                f"{settings.MCP_ML_BASE_URL}/models/{model_id}/deploy",
                json=payload,
                headers={"Authorization": f"Bearer {settings.MCP_ML_API_KEY}"},
                verify=settings.MCP_ML_VERIFY_SSL,
            )
            if resp.status_code == 404:
                return json.dumps({"error": "NotFound", "details": f"Model {model_id} not found"})
            resp.raise_for_status()
            return json.dumps({"status": "ok", "data": resp.json()})
    except httpx.HTTPError as e:
        return json.dumps({"error": "HTTPError", "details": str(e)})
    except Exception as e:
        return json.dumps({"error": "Exception", "details": str(e)})


async def predict(model_id: str, input_data: dict[str, Any]) -> str:
    """Run inference on model.

    Args:
        model_id: Model identifier
        input_data: Input features

    Returns: JSON with predictions
    """
    try:
        payload = {"data": input_data}
        async with httpx.AsyncClient(timeout=settings.MCP_ML_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                f"{settings.MCP_ML_BASE_URL}/models/{model_id}/predict",
                json=payload,
                headers={"Authorization": f"Bearer {settings.MCP_ML_API_KEY}"},
                verify=settings.MCP_ML_VERIFY_SSL,
            )
            if resp.status_code == 404:
                return json.dumps({"error": "NotFound", "details": f"Model {model_id} not found"})
            resp.raise_for_status()
            return json.dumps({"status": "ok", "data": resp.json()})
    except httpx.HTTPError as e:
        return json.dumps({"error": "HTTPError", "details": str(e)})
    except Exception as e:
        return json.dumps({"error": "Exception", "details": str(e)})


async def list_experiments(model_id: str) -> str:
    """List experiments for a model.

    Args:
        model_id: Model identifier

    Returns: JSON with experiments
    """
    try:
        async with httpx.AsyncClient(timeout=settings.MCP_ML_TIMEOUT_SECONDS) as client:
            resp = await client.get(
                f"{settings.MCP_ML_BASE_URL}/models/{model_id}/experiments",
                headers={"Authorization": f"Bearer {settings.MCP_ML_API_KEY}"},
                verify=settings.MCP_ML_VERIFY_SSL,
            )
            if resp.status_code == 404:
                return json.dumps({"error": "NotFound", "details": f"Model {model_id} not found"})
            resp.raise_for_status()
            return json.dumps({"status": "ok", "data": resp.json()})
    except httpx.HTTPError as e:
        return json.dumps({"error": "HTTPError", "details": str(e)})
    except Exception as e:
        return json.dumps({"error": "Exception", "details": str(e)})
