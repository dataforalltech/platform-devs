"""Tests for connectors tools."""

import json
from unittest.mock import MagicMock

import pytest

from src.tools import connectors_tools


@pytest.mark.asyncio
async def test_connectors_health_check(mock_api_client: MagicMock) -> None:
    """Test health check tool."""
    result = await connectors_tools.connectors_health_check()
    assert len(result) == 1
    assert result[0].type == "text"
    data = json.loads(result[0].text)
    assert data["status"] == "ok"
    mock_api_client.get.assert_called_once_with("/api/health")


@pytest.mark.asyncio
async def test_connectors_list(mock_api_client: MagicMock) -> None:
    """Test list connectors tool."""
    result = await connectors_tools.connectors_list()
    assert len(result) == 1
    assert result[0].type == "text"
    mock_api_client.get.assert_called_once_with("/api/v1/connectors")


@pytest.mark.asyncio
async def test_connectors_get(mock_api_client: MagicMock) -> None:
    """Test get connector tool."""
    result = await connectors_tools.connectors_get("salesforce")
    assert len(result) == 1
    assert result[0].type == "text"
    mock_api_client.get.assert_called_once_with("/api/v1/connectors/salesforce")


@pytest.mark.asyncio
async def test_connectors_search(mock_api_client: MagicMock) -> None:
    """Test search connectors tool."""
    result = await connectors_tools.connectors_search("google")
    assert len(result) == 1
    assert result[0].type == "text"
    mock_api_client.get.assert_called_once_with(
        "/api/v1/connectors/search",
        params={"q": "google"},
    )


@pytest.mark.asyncio
async def test_connectors_get_schema(mock_api_client: MagicMock) -> None:
    """Test get schema tool."""
    result = await connectors_tools.connectors_get_schema("salesforce")
    assert len(result) == 1
    assert result[0].type == "text"
    mock_api_client.get.assert_called_once_with("/api/v1/connectors/salesforce/schema")


@pytest.mark.asyncio
async def test_connectors_test_connection(mock_api_client: MagicMock) -> None:
    """Test connection tool."""
    credentials = {"api_key": "test-key", "url": "https://api.example.com"}
    result = await connectors_tools.connectors_test_connection("salesforce", credentials)
    assert len(result) == 1
    assert result[0].type == "text"
    data = json.loads(result[0].text)
    assert data["status"] == "ok"
    mock_api_client.post.assert_called_once_with(
        "/api/v1/connectors/salesforce/test",
        json=credentials,
    )


@pytest.mark.asyncio
async def test_connectors_list_credentials(mock_api_client: MagicMock) -> None:
    """Test list credentials tool."""
    result = await connectors_tools.connectors_list_credentials()
    assert len(result) == 1
    assert result[0].type == "text"
    mock_api_client.get.assert_called_once_with("/api/v1/credentials")


@pytest.mark.asyncio
async def test_connectors_get_credential(mock_api_client: MagicMock) -> None:
    """Test get credential tool."""
    result = await connectors_tools.connectors_get_credential("cred-123")
    assert len(result) == 1
    assert result[0].type == "text"
    mock_api_client.get.assert_called_once_with("/api/v1/credentials/cred-123")


@pytest.mark.asyncio
async def test_connectors_health_check_error(mock_api_client: MagicMock) -> None:
    """Test health check with error response."""
    mock_api_client.get.return_value.status_code = 500
    result = await connectors_tools.connectors_health_check()
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["error"] == "HealthCheckFailed"
    assert "500" in data["details"]


@pytest.mark.asyncio
async def test_connectors_get_not_found(mock_api_client: MagicMock) -> None:
    """Test get connector with 404 response."""
    mock_api_client.get.return_value.status_code = 404
    result = await connectors_tools.connectors_get("nonexistent")
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["error"] == "NotFound"
    assert "nonexistent" in data["details"]


@pytest.mark.asyncio
async def test_connectors_list_exception(mock_api_client: MagicMock) -> None:
    """Test list connectors with exception."""
    mock_api_client.get.side_effect = Exception("Connection timeout")
    result = await connectors_tools.connectors_list()
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["error"] == "InternalError"


@pytest.mark.asyncio
async def test_connectors_test_connection_error(mock_api_client: MagicMock) -> None:
    """Test connection with failure response."""
    mock_api_client.post.return_value.status_code = 400
    result = await connectors_tools.connectors_test_connection("salesforce", {"invalid": "config"})
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert "error" in data or "failed" in str(data).lower()


@pytest.mark.asyncio
async def test_connectors_list_credentials_exception(mock_api_client: MagicMock) -> None:
    """Test list credentials with exception."""
    mock_api_client.get.side_effect = Exception("Credential vault unavailable")
    result = await connectors_tools.connectors_list_credentials()
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["error"] == "InternalError"


@pytest.mark.asyncio
async def test_connectors_health_check_exception(mock_api_client: MagicMock) -> None:
    """Test health check with exception."""
    mock_api_client.get.side_effect = Exception("Service unavailable")
    result = await connectors_tools.connectors_health_check()
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["error"] == "InternalError"


@pytest.mark.asyncio
async def test_connectors_get_403_forbidden(mock_api_client: MagicMock) -> None:
    """Test get connector with 403 Forbidden."""
    mock_api_client.get.return_value.status_code = 403
    result = await connectors_tools.connectors_get("connector123")
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert "error" in data or "forbidden" in str(data).lower()


@pytest.mark.asyncio
async def test_connectors_search_exception(mock_api_client: MagicMock) -> None:
    """Test search connectors with exception."""
    mock_api_client.get.side_effect = Exception("Search service down")
    result = await connectors_tools.connectors_search("salesforce")
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["error"] == "InternalError"


@pytest.mark.asyncio
async def test_connectors_get_schema_exception(mock_api_client: MagicMock) -> None:
    """Test get schema with exception."""
    mock_api_client.get.side_effect = Exception("Schema service unavailable")
    result = await connectors_tools.connectors_get_schema("salesforce")
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["error"] == "InternalError"


@pytest.mark.asyncio
async def test_connectors_get_schema_404(mock_api_client: MagicMock) -> None:
    """Test get schema with 404 Not Found."""
    mock_api_client.get.return_value.status_code = 404
    result = await connectors_tools.connectors_get_schema("nonexistent")
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["error"] == "NotFound"


@pytest.mark.asyncio
async def test_connectors_test_connection_exception(mock_api_client: MagicMock) -> None:
    """Test connection with exception."""
    mock_api_client.post.side_effect = Exception("Connection test failed")
    result = await connectors_tools.connectors_test_connection("salesforce", {})
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["error"] == "InternalError"


@pytest.mark.asyncio
async def test_connectors_get_credential_404(mock_api_client: MagicMock) -> None:
    """Test get credential with 404 Not Found."""
    mock_api_client.get.return_value.status_code = 404
    result = await connectors_tools.connectors_get_credential("nonexistent")
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert "error" in data or "not found" in str(data).lower()


@pytest.mark.asyncio
async def test_connectors_get_credential_exception(mock_api_client: MagicMock) -> None:
    """Test get credential with exception."""
    mock_api_client.get.side_effect = Exception("Credential service down")
    result = await connectors_tools.connectors_get_credential("cred-123")
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["error"] == "InternalError"


@pytest.mark.asyncio
async def test_connectors_search_500(mock_api_client: MagicMock) -> None:
    """Test search connectors with 500 error."""
    mock_api_client.get.return_value.status_code = 500
    result = await connectors_tools.connectors_search("google")
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert "error" in data or data.get("status") == "error"


@pytest.mark.asyncio
async def test_connectors_list_connectors_500(mock_api_client: MagicMock) -> None:
    """Test list connectors with 500 error."""
    mock_api_client.get.return_value.status_code = 500
    result = await connectors_tools.connectors_list()
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert "error" in data or data.get("status") == "error"
