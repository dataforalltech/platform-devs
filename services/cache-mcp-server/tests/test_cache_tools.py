"""Tests for cache tools."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_cache_health_check_success(mock_api_client: MagicMock) -> None:
    """Test successful health check."""
    from src.tools.cache_tools import cache_health_check

    mock_api_client.get.return_value.status_code = 200
    mock_api_client.get.return_value.json.return_value = {"status": "healthy"}

    result = await cache_health_check()

    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["status"] == "ok"
    assert data["data"]["status"] == "healthy"
    mock_api_client.get.assert_called_once_with("/health")


@pytest.mark.asyncio
async def test_cache_health_check_failure(mock_api_client: MagicMock) -> None:
    """Test health check with server error."""
    from src.tools.cache_tools import cache_health_check

    mock_api_client.get.return_value.status_code = 500

    result = await cache_health_check()

    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["error"] == "HealthCheckFailed"
    assert "Status 500" in data["details"]


@pytest.mark.asyncio
async def test_cache_health_check_exception(mock_api_client: MagicMock) -> None:
    """Test health check with exception."""
    from src.tools.cache_tools import cache_health_check

    mock_api_client.get.side_effect = Exception("Connection error")

    result = await cache_health_check()

    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["error"] == "InternalError"
    assert "Connection error" in data["details"]


@pytest.mark.asyncio
async def test_cache_set_success(mock_api_client: MagicMock) -> None:
    """Test successful cache set."""
    from src.tools.cache_tools import cache_set

    mock_api_client.post.return_value.status_code = 200
    mock_api_client.post.return_value.json.return_value = {"key": "test", "status": "set"}

    result = await cache_set(key="test", value="value")

    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["status"] == "set"
    mock_api_client.post.assert_called_once()
    call_args = mock_api_client.post.call_args
    assert call_args[1]["json"]["key"] == "test"
    assert call_args[1]["json"]["value"] == "value"


@pytest.mark.asyncio
async def test_cache_set_with_ttl(mock_api_client: MagicMock) -> None:
    """Test cache set with TTL."""
    from src.tools.cache_tools import cache_set

    mock_api_client.post.return_value.status_code = 200
    mock_api_client.post.return_value.json.return_value = {"key": "test", "ttl": 3600}

    result = await cache_set(key="test", value="value", ttl=3600)

    assert len(result) == 1
    call_args = mock_api_client.post.call_args
    assert call_args[1]["json"]["ttl"] == 3600


@pytest.mark.asyncio
async def test_cache_set_invalid_request(mock_api_client: MagicMock) -> None:
    """Test cache set with invalid request."""
    from src.tools.cache_tools import cache_set

    mock_api_client.post.return_value.status_code = 400

    result = await cache_set(key="", value="")

    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["error"] == "InvalidRequest"


@pytest.mark.asyncio
async def test_cache_set_server_error(mock_api_client: MagicMock) -> None:
    """Test cache set with server error."""
    from src.tools.cache_tools import cache_set

    mock_api_client.post.return_value.status_code = 500

    result = await cache_set(key="test", value="value")

    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["error"] == "SetFailed"


@pytest.mark.asyncio
async def test_cache_set_exception(mock_api_client: MagicMock) -> None:
    """Test cache set with exception."""
    from src.tools.cache_tools import cache_set

    mock_api_client.post.side_effect = Exception("Network error")

    result = await cache_set(key="test", value="value")

    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["error"] == "InternalError"


@pytest.mark.asyncio
async def test_cache_get_success(mock_api_client: MagicMock) -> None:
    """Test successful cache get."""
    from src.tools.cache_tools import cache_get

    mock_api_client.get.return_value.status_code = 200
    mock_api_client.get.return_value.json.return_value = {"key": "test", "value": "cached_value"}

    result = await cache_get(key="test")

    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["value"] == "cached_value"
    mock_api_client.get.assert_called_once_with("/cache/get/test")


@pytest.mark.asyncio
async def test_cache_get_not_found(mock_api_client: MagicMock) -> None:
    """Test cache get with key not found."""
    from src.tools.cache_tools import cache_get

    mock_api_client.get.return_value.status_code = 404

    result = await cache_get(key="missing")

    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["error"] == "KeyNotFound"
    assert "missing" in data["details"]


@pytest.mark.asyncio
async def test_cache_get_server_error(mock_api_client: MagicMock) -> None:
    """Test cache get with server error."""
    from src.tools.cache_tools import cache_get

    mock_api_client.get.return_value.status_code = 500

    result = await cache_get(key="test")

    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["error"] == "GetFailed"


@pytest.mark.asyncio
async def test_cache_get_exception(mock_api_client: MagicMock) -> None:
    """Test cache get with exception."""
    from src.tools.cache_tools import cache_get

    mock_api_client.get.side_effect = Exception("Timeout")

    result = await cache_get(key="test")

    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["error"] == "InternalError"


@pytest.mark.asyncio
async def test_cache_delete_success(mock_api_client: MagicMock) -> None:
    """Test successful cache delete."""
    from src.tools.cache_tools import cache_delete

    mock_api_client.delete.return_value.status_code = 200
    mock_api_client.delete.return_value.json.return_value = {"deleted": True}

    result = await cache_delete(key="test")

    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["deleted"] is True
    mock_api_client.delete.assert_called_once_with("/cache/delete/test")


@pytest.mark.asyncio
async def test_cache_delete_not_found(mock_api_client: MagicMock) -> None:
    """Test cache delete with key not found."""
    from src.tools.cache_tools import cache_delete

    mock_api_client.delete.return_value.status_code = 404

    result = await cache_delete(key="missing")

    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["error"] == "KeyNotFound"


@pytest.mark.asyncio
async def test_cache_delete_server_error(mock_api_client: MagicMock) -> None:
    """Test cache delete with server error."""
    from src.tools.cache_tools import cache_delete

    mock_api_client.delete.return_value.status_code = 500

    result = await cache_delete(key="test")

    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["error"] == "DeleteFailed"


@pytest.mark.asyncio
async def test_cache_delete_exception(mock_api_client: MagicMock) -> None:
    """Test cache delete with exception."""
    from src.tools.cache_tools import cache_delete

    mock_api_client.delete.side_effect = Exception("Connection refused")

    result = await cache_delete(key="test")

    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["error"] == "InternalError"


@pytest.mark.asyncio
async def test_cache_clear_all_success(mock_api_client: MagicMock) -> None:
    """Test successful cache clear all."""
    from src.tools.cache_tools import cache_clear_all

    mock_api_client.delete.return_value.status_code = 200
    mock_api_client.delete.return_value.json.return_value = {"cleared": True, "entries": 42}

    result = await cache_clear_all()

    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["cleared"] is True
    assert data["entries"] == 42
    mock_api_client.delete.assert_called_once_with("/cache/clear")


@pytest.mark.asyncio
async def test_cache_clear_all_server_error(mock_api_client: MagicMock) -> None:
    """Test cache clear all with server error."""
    from src.tools.cache_tools import cache_clear_all

    mock_api_client.delete.return_value.status_code = 500

    result = await cache_clear_all()

    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["error"] == "ClearFailed"


@pytest.mark.asyncio
async def test_cache_clear_all_exception(mock_api_client: MagicMock) -> None:
    """Test cache clear all with exception."""
    from src.tools.cache_tools import cache_clear_all

    mock_api_client.delete.side_effect = Exception("I/O error")

    result = await cache_clear_all()

    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["error"] == "InternalError"


@pytest.mark.asyncio
async def test_cache_get_stats_success(mock_api_client: MagicMock) -> None:
    """Test successful cache get stats."""
    from src.tools.cache_tools import cache_get_stats

    mock_api_client.get.return_value.status_code = 200
    mock_api_client.get.return_value.json.return_value = {
        "hits": 1000,
        "misses": 100,
        "hit_rate": 0.91,
    }

    result = await cache_get_stats()

    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["hits"] == 1000
    assert data["misses"] == 100
    mock_api_client.get.assert_called_once_with("/cache/stats")


@pytest.mark.asyncio
async def test_cache_get_stats_server_error(mock_api_client: MagicMock) -> None:
    """Test cache get stats with server error."""
    from src.tools.cache_tools import cache_get_stats

    mock_api_client.get.return_value.status_code = 503

    result = await cache_get_stats()

    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["error"] == "StatsFailed"


@pytest.mark.asyncio
async def test_cache_get_stats_exception(mock_api_client: MagicMock) -> None:
    """Test cache get stats with exception."""
    from src.tools.cache_tools import cache_get_stats

    mock_api_client.get.side_effect = Exception("Database connection failed")

    result = await cache_get_stats()

    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["error"] == "InternalError"


@pytest.mark.asyncio
async def test_cache_set_pattern_success(mock_api_client: MagicMock) -> None:
    """Test successful cache set pattern."""
    from src.tools.cache_tools import cache_set_pattern

    mock_api_client.post.return_value.status_code = 200
    mock_api_client.post.return_value.json.return_value = {
        "pattern": "user:123:*",
        "set_count": 3,
    }

    result = await cache_set_pattern(
        pattern="user:123:*",
        values={"name": "John", "email": "john@example.com", "role": "admin"},
    )

    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["set_count"] == 3
    call_args = mock_api_client.post.call_args
    assert call_args[1]["json"]["pattern"] == "user:123:*"
    assert "name" in call_args[1]["json"]["values"]


@pytest.mark.asyncio
async def test_cache_set_pattern_with_ttl(mock_api_client: MagicMock) -> None:
    """Test cache set pattern with TTL."""
    from src.tools.cache_tools import cache_set_pattern

    mock_api_client.post.return_value.status_code = 200
    mock_api_client.post.return_value.json.return_value = {"set_count": 2, "ttl": 7200}

    result = await cache_set_pattern(
        pattern="session:*",
        values={"token": "abc123", "user_id": "42"},
        ttl=7200,
    )

    assert len(result) == 1
    call_args = mock_api_client.post.call_args
    assert call_args[1]["json"]["ttl"] == 7200


@pytest.mark.asyncio
async def test_cache_set_pattern_invalid_request(mock_api_client: MagicMock) -> None:
    """Test cache set pattern with invalid request."""
    from src.tools.cache_tools import cache_set_pattern

    mock_api_client.post.return_value.status_code = 400

    result = await cache_set_pattern(pattern="", values={})

    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["error"] == "InvalidRequest"


@pytest.mark.asyncio
async def test_cache_set_pattern_server_error(mock_api_client: MagicMock) -> None:
    """Test cache set pattern with server error."""
    from src.tools.cache_tools import cache_set_pattern

    mock_api_client.post.return_value.status_code = 500

    result = await cache_set_pattern(pattern="test:*", values={"a": "1"})

    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["error"] == "SetPatternFailed"


@pytest.mark.asyncio
async def test_cache_set_pattern_exception(mock_api_client: MagicMock) -> None:
    """Test cache set pattern with exception."""
    from src.tools.cache_tools import cache_set_pattern

    mock_api_client.post.side_effect = Exception("Memory limit exceeded")

    result = await cache_set_pattern(pattern="test:*", values={"a": "1"})

    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["error"] == "InternalError"


@pytest.mark.asyncio
async def test_cache_increment_success(mock_api_client: MagicMock) -> None:
    """Test successful cache increment."""
    from src.tools.cache_tools import cache_increment

    mock_api_client.put.return_value.status_code = 200
    mock_api_client.put.return_value.json.return_value = {"key": "counter", "value": 11}

    result = await cache_increment(key="counter", amount=1)

    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["value"] == 11
    call_args = mock_api_client.put.call_args
    assert call_args[1]["json"]["key"] == "counter"
    assert call_args[1]["json"]["amount"] == 1


@pytest.mark.asyncio
async def test_cache_increment_default_amount(mock_api_client: MagicMock) -> None:
    """Test cache increment with default amount."""
    from src.tools.cache_tools import cache_increment

    mock_api_client.put.return_value.status_code = 200
    mock_api_client.put.return_value.json.return_value = {"key": "counter", "value": 1}

    result = await cache_increment(key="counter")

    assert len(result) == 1
    call_args = mock_api_client.put.call_args
    assert call_args[1]["json"]["amount"] == 1


@pytest.mark.asyncio
async def test_cache_increment_invalid_request(mock_api_client: MagicMock) -> None:
    """Test cache increment with invalid request."""
    from src.tools.cache_tools import cache_increment

    mock_api_client.put.return_value.status_code = 400

    result = await cache_increment(key="", amount=-5)

    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["error"] == "InvalidRequest"


@pytest.mark.asyncio
async def test_cache_increment_not_found(mock_api_client: MagicMock) -> None:
    """Test cache increment with key not found."""
    from src.tools.cache_tools import cache_increment

    mock_api_client.put.return_value.status_code = 404

    result = await cache_increment(key="missing")

    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["error"] == "KeyNotFound"


@pytest.mark.asyncio
async def test_cache_increment_server_error(mock_api_client: MagicMock) -> None:
    """Test cache increment with server error."""
    from src.tools.cache_tools import cache_increment

    mock_api_client.put.return_value.status_code = 500

    result = await cache_increment(key="counter", amount=5)

    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["error"] == "IncrementFailed"


@pytest.mark.asyncio
async def test_cache_increment_exception(mock_api_client: MagicMock) -> None:
    """Test cache increment with exception."""
    from src.tools.cache_tools import cache_increment

    mock_api_client.put.side_effect = Exception("Race condition detected")

    result = await cache_increment(key="counter")

    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["error"] == "InternalError"
