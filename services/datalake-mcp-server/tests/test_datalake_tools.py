"""Tests for datalake tools."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from src.tools.datalake_tools import (
    create_table,
    drop_table,
    get_table_schema,
    get_table_stats,
    list_schemas,
    list_tables,
    query_data,
    validate_table,
)


@pytest.mark.asyncio
async def test_list_schemas_success(mock_http_client, mock_settings, mock_successful_response):
    """Test list_schemas with successful response."""
    mock_http_client.return_value.__aenter__.return_value.get = AsyncMock(
        return_value=mock_successful_response
    )

    result = await list_schemas("mydb")
    result_dict = json.loads(result)

    assert result_dict["status"] == "ok"
    assert "data" in result_dict


@pytest.mark.asyncio
async def test_list_schemas_not_found(mock_http_client, mock_settings, mock_not_found_response):
    """Test list_schemas with database not found."""
    mock_http_client.return_value.__aenter__.return_value.get = AsyncMock(
        return_value=mock_not_found_response
    )

    result = await list_schemas("nonexistent")
    result_dict = json.loads(result)

    assert result_dict["error"] == "NotFound"


@pytest.mark.asyncio
async def test_list_tables_success(mock_http_client, mock_settings, mock_successful_response):
    """Test list_tables with successful response."""
    mock_http_client.return_value.__aenter__.return_value.get = AsyncMock(
        return_value=mock_successful_response
    )

    result = await list_tables("mydb", "public")
    result_dict = json.loads(result)

    assert result_dict["status"] == "ok"


@pytest.mark.asyncio
async def test_get_table_schema_success(
    mock_http_client, mock_settings, mock_successful_response
):
    """Test get_table_schema with successful response."""
    mock_http_client.return_value.__aenter__.return_value.get = AsyncMock(
        return_value=mock_successful_response
    )

    result = await get_table_schema("mydb", "public", "users")
    result_dict = json.loads(result)

    assert result_dict["status"] == "ok"


@pytest.mark.asyncio
async def test_create_table_success(mock_http_client, mock_settings, mock_successful_response):
    """Test create_table with successful response."""
    mock_http_client.return_value.__aenter__.return_value.post = AsyncMock(
        return_value=mock_successful_response
    )

    columns = [
        {"name": "id", "type": "INT", "nullable": False},
        {"name": "name", "type": "VARCHAR(255)", "nullable": True},
    ]
    result = await create_table("mydb", "public", "users", columns)
    result_dict = json.loads(result)

    assert result_dict["status"] == "ok"


@pytest.mark.asyncio
async def test_create_table_bad_request(mock_http_client, mock_settings, mock_bad_request_response):
    """Test create_table with bad request."""
    mock_http_client.return_value.__aenter__.return_value.post = AsyncMock(
        return_value=mock_bad_request_response
    )

    columns = []
    result = await create_table("mydb", "public", "users", columns)
    result_dict = json.loads(result)

    assert result_dict["error"] == "BadRequest"


@pytest.mark.asyncio
async def test_drop_table_success(mock_http_client, mock_settings, mock_successful_response):
    """Test drop_table with successful response."""
    mock_http_client.return_value.__aenter__.return_value.delete = AsyncMock(
        return_value=mock_successful_response
    )

    result = await drop_table("mydb", "public", "users")
    result_dict = json.loads(result)

    assert result_dict["status"] == "ok"


@pytest.mark.asyncio
async def test_query_data_success(mock_http_client, mock_settings, mock_successful_response):
    """Test query_data with successful response."""
    mock_http_client.return_value.__aenter__.return_value.post = AsyncMock(
        return_value=mock_successful_response
    )

    result = await query_data("mydb", "SELECT * FROM users LIMIT 10")
    result_dict = json.loads(result)

    assert result_dict["status"] == "ok"


@pytest.mark.asyncio
async def test_query_data_with_limit(mock_http_client, mock_settings, mock_successful_response):
    """Test query_data with custom limit."""
    mock_http_client.return_value.__aenter__.return_value.post = AsyncMock(
        return_value=mock_successful_response
    )

    result = await query_data("mydb", "SELECT * FROM users", limit=100)
    result_dict = json.loads(result)

    assert result_dict["status"] == "ok"


@pytest.mark.asyncio
async def test_validate_table_success(mock_http_client, mock_settings, mock_successful_response):
    """Test validate_table with successful response."""
    mock_http_client.return_value.__aenter__.return_value.post = AsyncMock(
        return_value=mock_successful_response
    )

    result = await validate_table("mydb", "public", "users")
    result_dict = json.loads(result)

    assert result_dict["status"] == "ok"


@pytest.mark.asyncio
async def test_get_table_stats_success(mock_http_client, mock_settings, mock_successful_response):
    """Test get_table_stats with successful response."""
    mock_http_client.return_value.__aenter__.return_value.get = AsyncMock(
        return_value=mock_successful_response
    )

    result = await get_table_stats("mydb", "public", "users")
    result_dict = json.loads(result)

    assert result_dict["status"] == "ok"


@pytest.mark.asyncio
async def test_exception_handling(mock_http_client, mock_settings):
    """Test exception handling in tools."""
    mock_http_client.return_value.__aenter__.return_value.get = AsyncMock(
        side_effect=Exception("Network error")
    )

    result = await list_schemas("mydb")
    result_dict = json.loads(result)

    assert result_dict["error"] == "Exception"
    assert "Network error" in result_dict["details"]
