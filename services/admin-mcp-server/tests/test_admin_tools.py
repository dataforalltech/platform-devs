"""Tests for admin tools."""

import json
from unittest.mock import MagicMock

import pytest

from src.tools import admin_tools


@pytest.mark.asyncio
async def test_admin_health_check(mock_api_client: MagicMock) -> None:
    """Test health check tool."""
    result = await admin_tools.admin_health_check()
    assert len(result) == 1
    assert result[0].type == "text"
    data = json.loads(result[0].text)
    assert data["status"] == "ok"
    mock_api_client.get.assert_called_once_with("/api/health")


@pytest.mark.asyncio
async def test_admin_health_check_failure(mock_api_client: MagicMock) -> None:
    """Test health check tool with server error."""
    mock_api_client.get.return_value.status_code = 503
    result = await admin_tools.admin_health_check()
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["error"] == "HealthCheckFailed"


@pytest.mark.asyncio
async def test_admin_list_users(mock_api_client: MagicMock) -> None:
    """Test list users tool."""
    mock_api_client.get.return_value.json.return_value = {"users": []}
    result = await admin_tools.admin_list_users()
    assert len(result) == 1
    assert result[0].type == "text"
    data = json.loads(result[0].text)
    assert "users" in data
    mock_api_client.get.assert_called_once_with("/api/v1/users")


@pytest.mark.asyncio
async def test_admin_get_user(mock_api_client: MagicMock) -> None:
    """Test get user tool."""
    mock_api_client.get.return_value.json.return_value = {"id": "user-123", "email": "user@example.com"}
    result = await admin_tools.admin_get_user("user-123")
    assert len(result) == 1
    assert result[0].type == "text"
    data = json.loads(result[0].text)
    assert data["id"] == "user-123"
    mock_api_client.get.assert_called_once_with("/api/v1/users/user-123")


@pytest.mark.asyncio
async def test_admin_get_user_not_found(mock_api_client: MagicMock) -> None:
    """Test get user tool with not found."""
    mock_api_client.get.return_value.status_code = 404
    result = await admin_tools.admin_get_user("nonexistent")
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["error"] == "UserNotFound"


@pytest.mark.asyncio
async def test_admin_create_user(mock_api_client: MagicMock) -> None:
    """Test create user tool."""
    mock_api_client.post.return_value.status_code = 201
    mock_api_client.post.return_value.json.return_value = {"id": "new-user", "email": "new@example.com"}
    result = await admin_tools.admin_create_user("new@example.com", "New User")
    assert len(result) == 1
    assert result[0].type == "text"
    data = json.loads(result[0].text)
    assert data["id"] == "new-user"
    mock_api_client.post.assert_called_once_with(
        "/api/v1/users",
        json={"email": "new@example.com", "name": "New User"},
    )


@pytest.mark.asyncio
async def test_admin_create_user_with_domain(mock_api_client: MagicMock) -> None:
    """Test create user tool with domain."""
    mock_api_client.post.return_value.status_code = 201
    mock_api_client.post.return_value.json.return_value = {"id": "new-user"}
    await admin_tools.admin_create_user("new@example.com", "New User", "domain-123")
    mock_api_client.post.assert_called_once_with(
        "/api/v1/users",
        json={"email": "new@example.com", "name": "New User", "domain_id": "domain-123"},
    )


@pytest.mark.asyncio
async def test_admin_list_domains(mock_api_client: MagicMock) -> None:
    """Test list domains tool."""
    mock_api_client.get.return_value.json.return_value = {"domains": []}
    result = await admin_tools.admin_list_domains()
    assert len(result) == 1
    assert result[0].type == "text"
    data = json.loads(result[0].text)
    assert "domains" in data
    mock_api_client.get.assert_called_once_with("/api/v1/domains")


@pytest.mark.asyncio
async def test_admin_list_tenants(mock_api_client: MagicMock) -> None:
    """Test list tenants tool."""
    mock_api_client.get.return_value.json.return_value = {"tenants": []}
    result = await admin_tools.admin_list_tenants()
    assert len(result) == 1
    assert result[0].type == "text"
    data = json.loads(result[0].text)
    assert "tenants" in data
    mock_api_client.get.assert_called_once_with("/api/v1/tenants")


@pytest.mark.asyncio
async def test_admin_get_tenant(mock_api_client: MagicMock) -> None:
    """Test get tenant tool."""
    mock_api_client.get.return_value.json.return_value = {"id": "tenant-123", "name": "Test Tenant"}
    result = await admin_tools.admin_get_tenant("tenant-123")
    assert len(result) == 1
    assert result[0].type == "text"
    data = json.loads(result[0].text)
    assert data["id"] == "tenant-123"
    mock_api_client.get.assert_called_once_with("/api/v1/tenants/tenant-123")


@pytest.mark.asyncio
async def test_admin_get_tenant_not_found(mock_api_client: MagicMock) -> None:
    """Test get tenant tool with not found."""
    mock_api_client.get.return_value.status_code = 404
    result = await admin_tools.admin_get_tenant("nonexistent")
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["error"] == "TenantNotFound"


@pytest.mark.asyncio
async def test_admin_assign_role(mock_api_client: MagicMock) -> None:
    """Test assign role tool."""
    result = await admin_tools.admin_assign_role("user-123", "role-admin")
    assert len(result) == 1
    assert result[0].type == "text"
    data = json.loads(result[0].text)
    assert data["status"] == "ok"
    mock_api_client.post.assert_called_once_with(
        "/api/v1/users/user-123/roles",
        json={"role_id": "role-admin"},
    )


@pytest.mark.asyncio
async def test_admin_list_roles(mock_api_client: MagicMock) -> None:
    """Test list roles tool."""
    mock_api_client.get.return_value.json.return_value = {"roles": []}
    result = await admin_tools.admin_list_roles()
    assert len(result) == 1
    assert result[0].type == "text"
    data = json.loads(result[0].text)
    assert "roles" in data
    mock_api_client.get.assert_called_once_with("/api/v1/roles")


@pytest.mark.asyncio
async def test_admin_health_check_exception(mock_api_client: MagicMock) -> None:
    """Test health check with exception."""
    mock_api_client.get.side_effect = Exception("Connection error")
    result = await admin_tools.admin_health_check()
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["error"] == "InternalError"
    assert "Connection error" in data["details"]


@pytest.mark.asyncio
async def test_admin_list_users_error(mock_api_client: MagicMock) -> None:
    """Test list users with API error."""
    mock_api_client.get.return_value.status_code = 500
    result = await admin_tools.admin_list_users()
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert "error" in data


@pytest.mark.asyncio
async def test_admin_create_user_exception(mock_api_client: MagicMock) -> None:
    """Test create user with exception."""
    mock_api_client.post.side_effect = Exception("API unavailable")
    result = await admin_tools.admin_create_user("test@example.com", "password", "Test User")
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["error"] == "InternalError"


@pytest.mark.asyncio
async def test_admin_list_domains_exception(mock_api_client: MagicMock) -> None:
    """Test list domains with exception."""
    mock_api_client.get.side_effect = Exception("Network timeout")
    result = await admin_tools.admin_list_domains()
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["error"] == "InternalError"


@pytest.mark.asyncio
async def test_admin_list_tenants_error(mock_api_client: MagicMock) -> None:
    """Test list tenants with 403 Forbidden."""
    mock_api_client.get.return_value.status_code = 403
    result = await admin_tools.admin_list_tenants()
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert "error" in data


@pytest.mark.asyncio
async def test_admin_assign_role_exception(mock_api_client: MagicMock) -> None:
    """Test assign role with exception."""
    mock_api_client.post.side_effect = Exception("Service down")
    result = await admin_tools.admin_assign_role("user123", "admin")
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["error"] == "InternalError"


@pytest.mark.asyncio
async def test_admin_get_user_exception(mock_api_client: MagicMock) -> None:
    """Test get user with exception."""
    mock_api_client.get.side_effect = Exception("Database error")
    result = await admin_tools.admin_get_user("user-123")
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["error"] == "InternalError"


@pytest.mark.asyncio
async def test_admin_get_user_500(mock_api_client: MagicMock) -> None:
    """Test get user with 500 error."""
    mock_api_client.get.return_value.status_code = 500
    result = await admin_tools.admin_get_user("user-123")
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert "error" in data


@pytest.mark.asyncio
async def test_admin_list_roles_exception(mock_api_client: MagicMock) -> None:
    """Test list roles with exception."""
    mock_api_client.get.side_effect = Exception("Role service down")
    result = await admin_tools.admin_list_roles()
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["error"] == "InternalError"


@pytest.mark.asyncio
async def test_admin_list_roles_500(mock_api_client: MagicMock) -> None:
    """Test list roles with 500 error."""
    mock_api_client.get.return_value.status_code = 500
    result = await admin_tools.admin_list_roles()
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert "error" in data


@pytest.mark.asyncio
async def test_admin_create_user_409(mock_api_client: MagicMock) -> None:
    """Test create user with duplicate email (409 Conflict)."""
    mock_api_client.post.return_value.status_code = 409
    result = await admin_tools.admin_create_user("duplicate@example.com", "User Name")
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert "error" in data


@pytest.mark.asyncio
async def test_admin_list_tenants_exception(mock_api_client: MagicMock) -> None:
    """Test list tenants with exception."""
    mock_api_client.get.side_effect = Exception("Tenant service down")
    result = await admin_tools.admin_list_tenants()
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["error"] == "InternalError"


@pytest.mark.asyncio
async def test_admin_get_tenant_exception(mock_api_client: MagicMock) -> None:
    """Test get tenant with exception."""
    mock_api_client.get.side_effect = Exception("Service unavailable")
    result = await admin_tools.admin_get_tenant("tenant-123")
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["error"] == "InternalError"


@pytest.mark.asyncio
async def test_admin_assign_role_404(mock_api_client: MagicMock) -> None:
    """Test assign role with user not found."""
    mock_api_client.post.return_value.status_code = 404
    result = await admin_tools.admin_assign_role("nonexistent", "admin")
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert "error" in data or "not found" in str(data).lower()


@pytest.mark.asyncio
async def test_admin_get_tenant_500(mock_api_client: MagicMock) -> None:
    """Test get tenant with 500 error."""
    mock_api_client.get.return_value.status_code = 500
    result = await admin_tools.admin_get_tenant("tenant-123")
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert "error" in data
