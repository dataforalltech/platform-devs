"""Tests for analytics tools."""

import json
from unittest.mock import AsyncMock

import pytest

from src.tools.analytics_tools import (
    create_dashboard,
    export_dashboard,
    get_dashboard,
    get_metrics,
    list_dashboards,
    query_data,
    refresh_dashboard,
)


@pytest.mark.asyncio
async def test_list_dashboards_success(mock_http_client, mock_settings, mock_successful_response):
    """Test list_dashboards with successful response."""
    mock_http_client.return_value.__aenter__.return_value.get = AsyncMock(
        return_value=mock_successful_response
    )

    result = await list_dashboards("tenant_123")
    result_dict = json.loads(result)

    assert result_dict["status"] == "ok"


@pytest.mark.asyncio
async def test_get_dashboard_success(mock_http_client, mock_settings, mock_successful_response):
    """Test get_dashboard with successful response."""
    mock_http_client.return_value.__aenter__.return_value.get = AsyncMock(
        return_value=mock_successful_response
    )

    result = await get_dashboard("dashboard_123")
    result_dict = json.loads(result)

    assert result_dict["status"] == "ok"


@pytest.mark.asyncio
async def test_create_dashboard_success(mock_http_client, mock_settings, mock_successful_response):
    """Test create_dashboard with successful response."""
    mock_http_client.return_value.__aenter__.return_value.post = AsyncMock(
        return_value=mock_successful_response
    )

    result = await create_dashboard("My Dashboard", "Sales metrics", {"type": "grid"})
    result_dict = json.loads(result)

    assert result_dict["status"] == "ok"


@pytest.mark.asyncio
async def test_create_dashboard_bad_request(
    mock_http_client, mock_settings, mock_bad_request_response
):
    """Test create_dashboard with bad request."""
    mock_http_client.return_value.__aenter__.return_value.post = AsyncMock(
        return_value=mock_bad_request_response
    )

    result = await create_dashboard("", "", {})
    result_dict = json.loads(result)

    assert result_dict["error"] == "BadRequest"


@pytest.mark.asyncio
async def test_refresh_dashboard_success(mock_http_client, mock_settings, mock_successful_response):
    """Test refresh_dashboard with successful response."""
    mock_http_client.return_value.__aenter__.return_value.post = AsyncMock(
        return_value=mock_successful_response
    )

    result = await refresh_dashboard("dashboard_123")
    result_dict = json.loads(result)

    assert result_dict["status"] == "ok"


@pytest.mark.asyncio
async def test_get_metrics_success(mock_http_client, mock_settings, mock_successful_response):
    """Test get_metrics with successful response."""
    mock_http_client.return_value.__aenter__.return_value.get = AsyncMock(
        return_value=mock_successful_response
    )

    result = await get_metrics("dashboard_123", "revenue", "7d")
    result_dict = json.loads(result)

    assert result_dict["status"] == "ok"


@pytest.mark.asyncio
async def test_query_data_success(mock_http_client, mock_settings, mock_successful_response):
    """Test query_data with successful response."""
    mock_http_client.return_value.__aenter__.return_value.post = AsyncMock(
        return_value=mock_successful_response
    )

    result = await query_data("SELECT * FROM orders")
    result_dict = json.loads(result)

    assert result_dict["status"] == "ok"


@pytest.mark.asyncio
async def test_query_data_with_limit(mock_http_client, mock_settings, mock_successful_response):
    """Test query_data with custom limit."""
    mock_http_client.return_value.__aenter__.return_value.post = AsyncMock(
        return_value=mock_successful_response
    )

    result = await query_data("SELECT * FROM orders", limit=500)
    result_dict = json.loads(result)

    assert result_dict["status"] == "ok"


@pytest.mark.asyncio
async def test_export_dashboard_success(mock_http_client, mock_settings, mock_successful_response):
    """Test export_dashboard with successful response."""
    mock_http_client.return_value.__aenter__.return_value.post = AsyncMock(
        return_value=mock_successful_response
    )

    result = await export_dashboard("dashboard_123", "pdf")
    result_dict = json.loads(result)

    assert result_dict["status"] == "ok"


@pytest.mark.asyncio
async def test_export_dashboard_csv(mock_http_client, mock_settings, mock_successful_response):
    """Test export_dashboard with csv format."""
    mock_http_client.return_value.__aenter__.return_value.post = AsyncMock(
        return_value=mock_successful_response
    )

    result = await export_dashboard("dashboard_123", "csv")
    result_dict = json.loads(result)

    assert result_dict["status"] == "ok"


@pytest.mark.asyncio
async def test_get_dashboard_not_found(mock_http_client, mock_settings, mock_not_found_response):
    """Test get_dashboard with not found response."""
    mock_http_client.return_value.__aenter__.return_value.get = AsyncMock(
        return_value=mock_not_found_response
    )

    result = await get_dashboard("nonexistent")
    result_dict = json.loads(result)

    assert result_dict["error"] == "NotFound"


@pytest.mark.asyncio
async def test_exception_handling(mock_http_client, mock_settings):
    """Test exception handling in tools."""
    mock_http_client.return_value.__aenter__.return_value.get = AsyncMock(
        side_effect=Exception("Network error")
    )

    result = await get_dashboard("dashboard_123")
    result_dict = json.loads(result)

    assert result_dict["error"] == "Exception"
    assert "Network error" in result_dict["details"]
