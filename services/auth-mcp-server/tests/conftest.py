"""Pytest configuration and fixtures."""

import os
from unittest.mock import AsyncMock, MagicMock

import pytest

# Set environment variables before importing settings
os.environ.setdefault("MCP_AUTH_BASE_URL", "http://localhost:8001")
os.environ.setdefault("MCP_AUTH_INTERNAL_TOKEN", "test-token")
os.environ.setdefault("MCP_AUTH_LOG_LEVEL", "INFO")

from src.config.settings import Settings


@pytest.fixture
def test_settings() -> Settings:
    """Create test settings."""
    return Settings(
        base_url="http://localhost:8001",
        internal_token="test-token",
        log_level="INFO",
        request_timeout=30.0,
    )


@pytest.fixture
def mock_api_client(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Create a mocked API client for testing."""
    # Create a mock response
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json = MagicMock(return_value={"status": "ok"})

    # Create a mock client with async methods
    client = MagicMock()
    client.get = AsyncMock(return_value=mock_response)
    client.post = AsyncMock(return_value=mock_response)
    client.put = AsyncMock(return_value=mock_response)
    client.delete = AsyncMock(return_value=mock_response)
    client.close = AsyncMock()

    # Monkeypatch the lazy singleton
    monkeypatch.setattr("src.tools.auth_tools.api_client", client)

    return client
