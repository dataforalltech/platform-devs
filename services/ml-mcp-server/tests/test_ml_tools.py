"""Tests for ML tools."""

import json
from unittest.mock import AsyncMock

import pytest

from src.tools.ml_tools import (
    create_model,
    deploy_model,
    evaluate_model,
    get_model,
    get_training_status,
    list_experiments,
    list_models,
    predict,
    train_model,
)


@pytest.mark.asyncio
async def test_list_models_success(mock_http_client, mock_settings, mock_successful_response):
    """Test list_models with successful response."""
    mock_http_client.return_value.__aenter__.return_value.get = AsyncMock(
        return_value=mock_successful_response
    )

    result = await list_models("tenant_123")
    result_dict = json.loads(result)

    assert result_dict["status"] == "ok"


@pytest.mark.asyncio
async def test_get_model_success(mock_http_client, mock_settings, mock_successful_response):
    """Test get_model with successful response."""
    mock_http_client.return_value.__aenter__.return_value.get = AsyncMock(
        return_value=mock_successful_response
    )

    result = await get_model("model_123")
    result_dict = json.loads(result)

    assert result_dict["status"] == "ok"


@pytest.mark.asyncio
async def test_create_model_success(mock_http_client, mock_settings, mock_successful_response):
    """Test create_model with successful response."""
    mock_http_client.return_value.__aenter__.return_value.post = AsyncMock(
        return_value=mock_successful_response
    )

    result = await create_model("my_model", "classification", {"param1": "value1"})
    result_dict = json.loads(result)

    assert result_dict["status"] == "ok"


@pytest.mark.asyncio
async def test_create_model_bad_request(mock_http_client, mock_settings, mock_bad_request_response):
    """Test create_model with bad request."""
    mock_http_client.return_value.__aenter__.return_value.post = AsyncMock(
        return_value=mock_bad_request_response
    )

    result = await create_model("", "", {})
    result_dict = json.loads(result)

    assert result_dict["error"] == "BadRequest"


@pytest.mark.asyncio
async def test_train_model_success(mock_http_client, mock_settings, mock_successful_response):
    """Test train_model with successful response."""
    mock_http_client.return_value.__aenter__.return_value.post = AsyncMock(
        return_value=mock_successful_response
    )

    result = await train_model("model_123", "dataset_123")
    result_dict = json.loads(result)

    assert result_dict["status"] == "ok"


@pytest.mark.asyncio
async def test_train_model_with_hyperparams(mock_http_client, mock_settings, mock_successful_response):
    """Test train_model with hyperparameters."""
    mock_http_client.return_value.__aenter__.return_value.post = AsyncMock(
        return_value=mock_successful_response
    )

    result = await train_model("model_123", "dataset_123", {"lr": 0.001, "epochs": 100})
    result_dict = json.loads(result)

    assert result_dict["status"] == "ok"


@pytest.mark.asyncio
async def test_get_training_status_success(mock_http_client, mock_settings, mock_successful_response):
    """Test get_training_status with successful response."""
    mock_http_client.return_value.__aenter__.return_value.get = AsyncMock(
        return_value=mock_successful_response
    )

    result = await get_training_status("job_123")
    result_dict = json.loads(result)

    assert result_dict["status"] == "ok"


@pytest.mark.asyncio
async def test_evaluate_model_success(mock_http_client, mock_settings, mock_successful_response):
    """Test evaluate_model with successful response."""
    mock_http_client.return_value.__aenter__.return_value.post = AsyncMock(
        return_value=mock_successful_response
    )

    result = await evaluate_model("model_123", "test_dataset_123")
    result_dict = json.loads(result)

    assert result_dict["status"] == "ok"


@pytest.mark.asyncio
async def test_deploy_model_success(mock_http_client, mock_settings, mock_successful_response):
    """Test deploy_model with successful response."""
    mock_http_client.return_value.__aenter__.return_value.post = AsyncMock(
        return_value=mock_successful_response
    )

    result = await deploy_model("model_123", "v1.0", "prod")
    result_dict = json.loads(result)

    assert result_dict["status"] == "ok"


@pytest.mark.asyncio
async def test_predict_success(mock_http_client, mock_settings, mock_successful_response):
    """Test predict with successful response."""
    mock_http_client.return_value.__aenter__.return_value.post = AsyncMock(
        return_value=mock_successful_response
    )

    result = await predict("model_123", {"feature1": 10, "feature2": 20})
    result_dict = json.loads(result)

    assert result_dict["status"] == "ok"


@pytest.mark.asyncio
async def test_list_experiments_success(mock_http_client, mock_settings, mock_successful_response):
    """Test list_experiments with successful response."""
    mock_http_client.return_value.__aenter__.return_value.get = AsyncMock(
        return_value=mock_successful_response
    )

    result = await list_experiments("model_123")
    result_dict = json.loads(result)

    assert result_dict["status"] == "ok"


@pytest.mark.asyncio
async def test_get_model_not_found(mock_http_client, mock_settings, mock_not_found_response):
    """Test get_model with not found response."""
    mock_http_client.return_value.__aenter__.return_value.get = AsyncMock(
        return_value=mock_not_found_response
    )

    result = await get_model("nonexistent")
    result_dict = json.loads(result)

    assert result_dict["error"] == "NotFound"


@pytest.mark.asyncio
async def test_exception_handling(mock_http_client, mock_settings):
    """Test exception handling in tools."""
    mock_http_client.return_value.__aenter__.return_value.get = AsyncMock(
        side_effect=Exception("Network error")
    )

    result = await get_model("model_123")
    result_dict = json.loads(result)

    assert result_dict["error"] == "Exception"
    assert "Network error" in result_dict["details"]
