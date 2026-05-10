"""Tests for API client."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import httpx

from src.config.settings import Settings
from src.client.api_client import CacheApiClient


@pytest.mark.asyncio
async def test_api_client_init() -> None:
    """Test API client initialization."""
    settings = Settings(base_url="http://localhost:8025", internal_token="test-token")

    with patch("src.client.api_client.httpx.AsyncClient") as mock_client_class:
        client = CacheApiClient(settings)

        assert client is not None
        mock_client_class.assert_called_once()
        call_kwargs = mock_client_class.call_args[1]
        assert call_kwargs["base_url"] == "http://localhost:8025"
        assert call_kwargs["headers"]["X-Internal-Token"] == "test-token"
        assert call_kwargs["timeout"] == 30.0


@pytest.mark.asyncio
async def test_api_client_init_no_token() -> None:
    """Test API client initialization without token."""
    settings = Settings(base_url="http://localhost:8025", internal_token="")

    with patch("src.client.api_client.httpx.AsyncClient") as mock_client_class:
        client = CacheApiClient(settings)

        assert client is not None
        call_kwargs = mock_client_class.call_args[1]
        assert "X-Internal-Token" not in call_kwargs["headers"]


@pytest.mark.asyncio
async def test_api_client_get() -> None:
    """Test GET request."""
    settings = Settings()

    with patch("src.client.api_client.httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_response = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client_class.return_value = mock_client

        client = CacheApiClient(settings)
        response = await client.get("/test")

        assert response == mock_response
        mock_client.get.assert_called_once_with("/test")


@pytest.mark.asyncio
async def test_api_client_post() -> None:
    """Test POST request."""
    settings = Settings()

    with patch("src.client.api_client.httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_response = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client_class.return_value = mock_client

        client = CacheApiClient(settings)
        response = await client.post("/test", json={"key": "value"})

        assert response == mock_response
        mock_client.post.assert_called_once_with("/test", json={"key": "value"})


@pytest.mark.asyncio
async def test_api_client_put() -> None:
    """Test PUT request."""
    settings = Settings()

    with patch("src.client.api_client.httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_response = AsyncMock()
        mock_client.put.return_value = mock_response
        mock_client_class.return_value = mock_client

        client = CacheApiClient(settings)
        response = await client.put("/test", json={"amount": 5})

        assert response == mock_response
        mock_client.put.assert_called_once_with("/test", json={"amount": 5})


@pytest.mark.asyncio
async def test_api_client_delete() -> None:
    """Test DELETE request."""
    settings = Settings()

    with patch("src.client.api_client.httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_response = AsyncMock()
        mock_client.delete.return_value = mock_response
        mock_client_class.return_value = mock_client

        client = CacheApiClient(settings)
        response = await client.delete("/test")

        assert response == mock_response
        mock_client.delete.assert_called_once_with("/test")


@pytest.mark.asyncio
async def test_api_client_close() -> None:
    """Test closing the client."""
    settings = Settings()

    with patch("src.client.api_client.httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client_class.return_value = mock_client

        client = CacheApiClient(settings)
        await client.close()

        mock_client.aclose.assert_called_once()


@pytest.mark.asyncio
async def test_api_client_get_with_kwargs() -> None:
    """Test GET request with additional kwargs."""
    settings = Settings()

    with patch("src.client.api_client.httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_response = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client_class.return_value = mock_client

        client = CacheApiClient(settings)
        response = await client.get("/test", params={"filter": "active"})

        assert response == mock_response
        mock_client.get.assert_called_once_with("/test", params={"filter": "active"})


@pytest.mark.asyncio
async def test_api_client_post_with_kwargs() -> None:
    """Test POST request with additional kwargs."""
    settings = Settings()

    with patch("src.client.api_client.httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_response = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client_class.return_value = mock_client

        client = CacheApiClient(settings)
        response = await client.post("/test", json={"key": "value"}, headers={"X-Custom": "header"})

        assert response == mock_response
        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        assert call_args[1]["json"] == {"key": "value"}
        assert call_args[1]["headers"] == {"X-Custom": "header"}
