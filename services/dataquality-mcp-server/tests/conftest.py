"""Test configuration and fixtures for dataquality-mcp."""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_settings():
    """Mock settings for tests."""
    with patch("src.config.settings.settings") as mock:
        mock.MCP_DATAQUALITY_BASE_URL = "http://localhost:8008/api/v1"
        mock.MCP_DATAQUALITY_API_KEY = "test-key"
        mock.MCP_DATAQUALITY_TIMEOUT_SECONDS = 60
        yield mock


@pytest.fixture
def mock_http_client():
    """Mock httpx AsyncClient."""
    with patch("src.tools.dataquality_tools.httpx.AsyncClient") as mock:
        yield mock


@pytest.fixture
def mock_successful_response():
    """Create a mock successful HTTP response."""
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"status": "ok", "data": []}
    return response


@pytest.fixture
def mock_not_found_response():
    """Create a mock 404 response."""
    response = MagicMock()
    response.status_code = 404
    return response


@pytest.fixture
def mock_bad_request_response():
    """Create a mock 400 response."""
    response = MagicMock()
    response.status_code = 400
    response.text = "Invalid request"
    return response
