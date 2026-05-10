"""Test configuration and fixtures."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def mock_http_client():
    """Mock httpx.AsyncClient."""
    return AsyncMock()


@pytest.fixture
def mock_settings():
    """Mock settings."""
    with patch("src.config.settings.settings") as mock:
        mock.MCP_PIPELINE_BASE_URL = "http://localhost:8003/api/v1"
        mock.MCP_PIPELINE_API_KEY = "test-key"
        mock.MCP_PIPELINE_TIMEOUT_SECONDS = 120
        yield mock
