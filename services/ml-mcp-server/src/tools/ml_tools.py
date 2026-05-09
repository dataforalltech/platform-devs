"""ML tools — model training, evaluation, and inference."""

import json
from typing import Any

import httpx

from src.config.settings import settings


async def ml_train_model(dataset_id: str, model_type: str, hyperparameters: dict[str, Any] | None = None) -> str:
    """Train a new machine learning model.

    Args:
        dataset_id: ID of the prepared dataset
        model_type: Type of model (classification, regression, clustering)
        hyperparameters: Optional model hyperparameters

    Returns: JSON with trained model info
    """
    try:
        payload = {
            "dataset_id": dataset_id,
            "model_type": model_type,
            "hyperparameters": hyperparameters or {},
        }
        async with httpx.AsyncClient(timeout=settings.MCP_ML_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                f"{settings.MCP_ML_BASE_URL}/models/train",
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


async def ml_evaluate_model(model_id: str, test_dataset_id: str) -> str:
    """Evaluate trained model on test dataset.

    Args:
        model_id: ID of the trained model
        test_dataset_id: ID of the test dataset

    Returns: JSON with evaluation metrics
    """
    try:
        payload = {
            "test_dataset_id": test_dataset_id,
        }
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


async def ml_get_model(model_id: str) -> str:
    """Get model details and metadata.

    Args:
        model_id: ID of the model

    Returns: JSON with model information
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


async def ml_list_models() -> str:
    """List all trained models.

    Returns: JSON with list of models
    """
    try:
        async with httpx.AsyncClient(timeout=settings.MCP_ML_TIMEOUT_SECONDS) as client:
            resp = await client.get(
                f"{settings.MCP_ML_BASE_URL}/models",
                headers={"Authorization": f"Bearer {settings.MCP_ML_API_KEY}"},
                verify=settings.MCP_ML_VERIFY_SSL,
            )
            resp.raise_for_status()
            return json.dumps({"status": "ok", "data": resp.json()})
    except httpx.HTTPError as e:
        return json.dumps({"error": "HTTPError", "details": str(e)})
    except Exception as e:
        return json.dumps({"error": "Exception", "details": str(e)})


async def ml_predict(model_id: str, data: dict[str, Any]) -> str:
    """Run inference on trained model.

    Args:
        model_id: ID of the trained model
        data: Input data for prediction

    Returns: JSON with predictions
    """
    try:
        payload = {"data": data}
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


async def ml_delete_model(model_id: str) -> str:
    """Delete a model.

    Args:
        model_id: ID of the model to delete

    Returns: JSON with deletion confirmation
    """
    try:
        async with httpx.AsyncClient(timeout=settings.MCP_ML_TIMEOUT_SECONDS) as client:
            resp = await client.delete(
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


async def ml_get_feature_importance(model_id: str) -> str:
    """Get feature importance for trained model (regression/classification).

    Args:
        model_id: ID of the trained model

    Returns: JSON with feature importance rankings
    """
    try:
        async with httpx.AsyncClient(timeout=settings.MCP_ML_TIMEOUT_SECONDS) as client:
            resp = await client.get(
                f"{settings.MCP_ML_BASE_URL}/models/{model_id}/feature-importance",
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


async def ml_export_model(model_id: str, format: str = "onnx") -> str:
    """Export trained model in specified format.

    Args:
        model_id: ID of the model
        format: Export format (onnx, pkl, tf, pytorch)

    Returns: JSON with export URL
    """
    try:
        async with httpx.AsyncClient(timeout=settings.MCP_ML_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                f"{settings.MCP_ML_BASE_URL}/models/{model_id}/export",
                json={"format": format},
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


async def ml_batch_predict(model_id: str, dataset_id: str) -> str:
    """Run batch inference on entire dataset.

    Args:
        model_id: ID of the trained model
        dataset_id: ID of the dataset for predictions

    Returns: JSON with job ID and status
    """
    try:
        payload = {"dataset_id": dataset_id}
        async with httpx.AsyncClient(timeout=settings.MCP_ML_TIMEOUT_SECONDS * 2) as client:
            resp = await client.post(
                f"{settings.MCP_ML_BASE_URL}/models/{model_id}/batch-predict",
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
