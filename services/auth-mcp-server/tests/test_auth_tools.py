"""Tests for auth tools."""

import json
from unittest.mock import MagicMock

import pytest

from src.tools import auth_tools


@pytest.mark.asyncio
async def test_auth_health_check(mock_api_client: MagicMock) -> None:
    """Test health check tool."""
    result = await auth_tools.auth_health_check()
    assert len(result) == 1
    assert result[0].type == "text"
    data = json.loads(result[0].text)
    assert data["status"] == "ok"
    mock_api_client.get.assert_called_once_with("/api/health")


@pytest.mark.asyncio
async def test_auth_check_email(mock_api_client: MagicMock) -> None:
    """Test check email tool."""
    result = await auth_tools.auth_check_email("test@example.com")
    assert len(result) == 1
    assert result[0].type == "text"
    mock_api_client.post.assert_called_once_with(
        "/api/v1/auth/check-email",
        json={"email": "test@example.com"},
    )


@pytest.mark.asyncio
async def test_auth_list_tenants(mock_api_client: MagicMock) -> None:
    """Test list tenants tool."""
    result = await auth_tools.auth_list_tenants()
    assert len(result) == 1
    assert result[0].type == "text"
    mock_api_client.get.assert_called_once_with("/api/v1/auth/tenants")


@pytest.mark.asyncio
async def test_auth_login(mock_api_client: MagicMock) -> None:
    """Test login tool."""
    result = await auth_tools.auth_login(
        email="test@example.com",
        password="password123",
    )
    assert len(result) == 1
    assert result[0].type == "text"
    mock_api_client.post.assert_called_once_with(
        "/api/v1/auth/login",
        json={"email": "test@example.com", "password": "password123"},
    )


@pytest.mark.asyncio
async def test_auth_get_me(mock_api_client: MagicMock) -> None:
    """Test get me tool."""
    result = await auth_tools.auth_get_me("Bearer token123")
    assert len(result) == 1
    assert result[0].type == "text"
    mock_api_client.get.assert_called_once_with(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer token123"},
    )


@pytest.mark.asyncio
async def test_auth_get_permissions(mock_api_client: MagicMock) -> None:
    """Test get permissions tool."""
    result = await auth_tools.auth_get_permissions("Bearer token123")
    assert len(result) == 1
    assert result[0].type == "text"
    mock_api_client.get.assert_called_once_with(
        "/api/v1/auth/me/permissions",
        headers={"Authorization": "Bearer token123"},
    )


@pytest.mark.asyncio
async def test_auth_refresh_token(mock_api_client: MagicMock) -> None:
    """Test refresh token tool."""
    result = await auth_tools.auth_refresh_token("refresh123")
    assert len(result) == 1
    assert result[0].type == "text"
    mock_api_client.post.assert_called_once_with(
        "/api/v1/auth/refresh",
        json={"refresh_token": "refresh123"},
    )


@pytest.mark.asyncio
async def test_auth_logout(mock_api_client: MagicMock) -> None:
    """Test logout tool."""
    result = await auth_tools.auth_logout("refresh123")
    assert len(result) == 1
    assert result[0].type == "text"
    data = json.loads(result[0].text)
    assert data["status"] == "ok"
    mock_api_client.post.assert_called_once_with(
        "/api/v1/auth/logout",
        json={"refresh_token": "refresh123"},
    )


@pytest.mark.asyncio
async def test_auth_get_service_token(mock_api_client: MagicMock) -> None:
    """Test get service token tool."""
    result = await auth_tools.auth_get_service_token("service-id", "secret")
    assert len(result) == 1
    assert result[0].type == "text"
    mock_api_client.post.assert_called_once_with(
        "/internal/service-tokens",
        json={"service_id": "service-id", "service_secret": "secret"},
    )


@pytest.mark.asyncio
async def test_auth_validate_token(mock_api_client: MagicMock) -> None:
    """Test validate token tool."""
    result = await auth_tools.auth_validate_token("Bearer token123")
    assert len(result) == 1
    assert result[0].type == "text"
    data = json.loads(result[0].text)
    assert data["valid"] is True
    mock_api_client.get.assert_called_once_with(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer token123"},
    )


@pytest.mark.asyncio
async def test_auth_health_check_error(mock_api_client: MagicMock) -> None:
    """Test health check with error response."""
    mock_api_client.get.return_value.status_code = 500
    result = await auth_tools.auth_health_check()
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["error"] == "HealthCheckFailed"
    assert "500" in data["details"]


@pytest.mark.asyncio
async def test_auth_health_check_exception(mock_api_client: MagicMock) -> None:
    """Test health check when API client raises exception."""
    mock_api_client.get.side_effect = Exception("Connection timeout")
    result = await auth_tools.auth_health_check()
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["error"] == "InternalError"
    assert "Connection timeout" in data["details"]


@pytest.mark.asyncio
async def test_auth_login_error(mock_api_client: MagicMock) -> None:
    """Test login with API error response."""
    mock_api_client.post.return_value.status_code = 401
    result = await auth_tools.auth_login("test@example.com", "wrong_password")
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["error"] == "LoginFailed"


@pytest.mark.asyncio
async def test_auth_login_exception(mock_api_client: MagicMock) -> None:
    """Test login when API client raises exception."""
    mock_api_client.post.side_effect = Exception("Network error")
    result = await auth_tools.auth_login("test@example.com", "password")
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["error"] == "InternalError"


@pytest.mark.asyncio
async def test_auth_validate_token_invalid(mock_api_client: MagicMock) -> None:
    """Test validate token with invalid token (401 response)."""
    mock_api_client.get.return_value.status_code = 401
    result = await auth_tools.auth_validate_token("Bearer invalid")
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["valid"] is False


@pytest.mark.asyncio
async def test_auth_get_me_exception(mock_api_client: MagicMock) -> None:
    """Test get me when API client raises exception."""
    mock_api_client.get.side_effect = Exception("API unavailable")
    result = await auth_tools.auth_get_me("Bearer token")
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["error"] == "InternalError"


@pytest.mark.asyncio
async def test_auth_get_permissions_error(mock_api_client: MagicMock) -> None:
    """Test get permissions with 403 Forbidden response."""
    mock_api_client.get.return_value.status_code = 403
    result = await auth_tools.auth_get_permissions("Bearer token")
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert "error" in data or data.get("status") == "error"


@pytest.mark.asyncio
async def test_auth_refresh_token_error(mock_api_client: MagicMock) -> None:
    """Test refresh token with invalid refresh token (401)."""
    mock_api_client.post.return_value.status_code = 401
    result = await auth_tools.auth_refresh_token("invalid_refresh")
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert "error" in data or data.get("status") != "ok"


@pytest.mark.asyncio
async def test_auth_logout_exception(mock_api_client: MagicMock) -> None:
    """Test logout when API client raises exception."""
    mock_api_client.post.side_effect = Exception("Service down")
    result = await auth_tools.auth_logout("refresh_token")
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["error"] == "InternalError"


@pytest.mark.asyncio
async def test_auth_health_check_400(mock_api_client: MagicMock) -> None:
    """Test health check with 400 Bad Request."""
    mock_api_client.get.return_value.status_code = 400
    result = await auth_tools.auth_health_check()
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["error"] == "HealthCheckFailed"


@pytest.mark.asyncio
async def test_auth_get_me_500(mock_api_client: MagicMock) -> None:
    """Test get me with 500 Internal Server Error."""
    mock_api_client.get.return_value.status_code = 500
    result = await auth_tools.auth_get_me("Bearer token")
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert "error" in data



@pytest.mark.asyncio
async def test_auth_list_tenants_exception(mock_api_client: MagicMock) -> None:
    """Test list tenants with exception."""
    mock_api_client.get.side_effect = Exception("Service down")
    result = await auth_tools.auth_list_tenants()
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["error"] == "InternalError"


@pytest.mark.asyncio
async def test_auth_get_service_token_exception(mock_api_client: MagicMock) -> None:
    """Test get service token with exception."""
    mock_api_client.post.side_effect = Exception("Auth server error")
    result = await auth_tools.auth_get_service_token("service", "secret")
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["error"] == "InternalError"


@pytest.mark.asyncio
async def test_auth_get_permissions_exception(mock_api_client: MagicMock) -> None:
    """Test get permissions with exception."""
    mock_api_client.get.side_effect = Exception("Permission check failed")
    result = await auth_tools.auth_get_permissions("Bearer token")
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["error"] == "InternalError"


@pytest.mark.asyncio
async def test_auth_check_email_403(mock_api_client: MagicMock) -> None:
    """Test check email with 403 Forbidden."""
    mock_api_client.post.return_value.status_code = 403
    result = await auth_tools.auth_check_email("test@example.com")
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert "error" in data or data.get("status") == "error"


@pytest.mark.asyncio
async def test_auth_login_403(mock_api_client: MagicMock) -> None:
    """Test login with 403 Forbidden."""
    mock_api_client.post.return_value.status_code = 403
    result = await auth_tools.auth_login("test@example.com", "pass")
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert "error" in data


@pytest.mark.asyncio
async def test_auth_refresh_token_exception(mock_api_client: MagicMock) -> None:
    """Test refresh token with exception."""
    mock_api_client.post.side_effect = Exception("Token service unavailable")
    result = await auth_tools.auth_refresh_token("refresh")
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["error"] == "InternalError"


@pytest.mark.asyncio
async def test_auth_validate_token_exception(mock_api_client: MagicMock) -> None:
    """Test validate token with exception."""
    mock_api_client.get.side_effect = Exception("Validation service error")
    result = await auth_tools.auth_validate_token("Bearer token")
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["error"] == "InternalError"


@pytest.mark.asyncio
async def test_auth_validate_token_500(mock_api_client: MagicMock) -> None:
    """Test validate token with 500 error."""
    mock_api_client.get.return_value.status_code = 500
    result = await auth_tools.auth_validate_token("Bearer token")
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert "error" in data or data.get("valid") is False


@pytest.mark.asyncio
async def test_auth_check_email_exception(mock_api_client: MagicMock) -> None:
    """Test check email with exception."""
    mock_api_client.post.side_effect = Exception("Email service down")
    result = await auth_tools.auth_check_email("test@example.com")
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["error"] == "InternalError"


@pytest.mark.asyncio
async def test_auth_check_email_404(mock_api_client: MagicMock) -> None:
    """Test check email with 404 Not Found."""
    mock_api_client.post.return_value.status_code = 404
    result = await auth_tools.auth_check_email("test@example.com")
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert "error" in data or data.get("status") == "error"


@pytest.mark.asyncio
async def test_auth_login_500(mock_api_client: MagicMock) -> None:
    """Test login with 500 Internal Server Error."""
    mock_api_client.post.return_value.status_code = 500
    result = await auth_tools.auth_login("test@example.com", "password")
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert "error" in data


@pytest.mark.asyncio
async def test_auth_get_me_403(mock_api_client: MagicMock) -> None:
    """Test get me with 403 Forbidden."""
    mock_api_client.get.return_value.status_code = 403
    result = await auth_tools.auth_get_me("Bearer token")
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert "error" in data


@pytest.mark.asyncio
async def test_auth_refresh_token_500(mock_api_client: MagicMock) -> None:
    """Test refresh token with 500 error."""
    mock_api_client.post.return_value.status_code = 500
    result = await auth_tools.auth_refresh_token("refresh_token")
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert "error" in data or data.get("status") == "error"


@pytest.mark.asyncio
async def test_auth_get_service_token_401(mock_api_client: MagicMock) -> None:
    """Test get service token with 401 Unauthorized."""
    mock_api_client.post.return_value.status_code = 401
    result = await auth_tools.auth_get_service_token("service-id", "secret")
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert "error" in data or data.get("status") == "error"


@pytest.mark.asyncio
async def test_auth_list_tenants_500(mock_api_client: MagicMock) -> None:
    """Test list tenants with 500 error."""
    mock_api_client.get.return_value.status_code = 500
    result = await auth_tools.auth_list_tenants()
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert "error" in data or data.get("status") == "error"


@pytest.mark.asyncio
async def test_auth_logout_403(mock_api_client: MagicMock) -> None:
    """Test logout with 403 Forbidden."""
    mock_api_client.post.return_value.status_code = 403
    result = await auth_tools.auth_logout("refresh_token")
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert "error" in data or data.get("status") == "error"

