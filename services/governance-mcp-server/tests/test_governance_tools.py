"""Tests for governance tools."""

import json
from unittest.mock import MagicMock

import pytest

from src.tools import governance_tools


@pytest.mark.asyncio
async def test_governance_health_check(mock_api_client: MagicMock) -> None:
    """Test health check tool."""
    result = await governance_tools.governance_health_check()
    assert len(result) == 1
    assert result[0].type == "text"
    data = json.loads(result[0].text)
    assert data["status"] == "ok"
    mock_api_client.get.assert_called_once_with("/api/health")


@pytest.mark.asyncio
async def test_governance_get_policy(mock_api_client: MagicMock) -> None:
    """Test get policy tool."""
    result = await governance_tools.governance_get_policy("policy-123")
    assert len(result) == 1
    assert result[0].type == "text"
    mock_api_client.get.assert_called_once_with("/api/v1/policies/policy-123")


@pytest.mark.asyncio
async def test_governance_list_policies(mock_api_client: MagicMock) -> None:
    """Test list policies tool."""
    result = await governance_tools.governance_list_policies()
    assert len(result) == 1
    assert result[0].type == "text"
    mock_api_client.get.assert_called_once_with("/api/v1/policies")


@pytest.mark.asyncio
async def test_governance_check_access(mock_api_client: MagicMock) -> None:
    """Test check access tool."""
    result = await governance_tools.governance_check_access(
        user_id="user-123",
        resource="resource-456",
        action="read",
    )
    assert len(result) == 1
    assert result[0].type == "text"
    mock_api_client.post.assert_called_once_with(
        "/api/v1/check-access",
        json={
            "user_id": "user-123",
            "resource": "resource-456",
            "action": "read",
        },
    )


@pytest.mark.asyncio
async def test_governance_list_permissions(mock_api_client: MagicMock) -> None:
    """Test list permissions tool."""
    result = await governance_tools.governance_list_permissions()
    assert len(result) == 1
    assert result[0].type == "text"
    mock_api_client.get.assert_called_once_with("/api/v1/permissions")


@pytest.mark.asyncio
async def test_governance_get_user_permissions(mock_api_client: MagicMock) -> None:
    """Test get user permissions tool."""
    result = await governance_tools.governance_get_user_permissions("user-123")
    assert len(result) == 1
    assert result[0].type == "text"
    mock_api_client.get.assert_called_once_with("/api/v1/users/user-123/permissions")


@pytest.mark.asyncio
async def test_governance_update_rls(mock_api_client: MagicMock) -> None:
    """Test update RLS tool."""
    rules = {"tenant_id": "tenant_abc", "conditions": ["user_id = :user_id"]}
    result = await governance_tools.governance_update_rls(
        resource="table_data",
        rules=rules,
    )
    assert len(result) == 1
    assert result[0].type == "text"
    data = json.loads(result[0].text)
    assert data["status"] == "ok"
    mock_api_client.post.assert_called_once_with(
        "/api/v1/rls",
        json={
            "resource": "table_data",
            "rules": rules,
        },
    )


@pytest.mark.asyncio
async def test_governance_get_rls(mock_api_client: MagicMock) -> None:
    """Test get RLS tool."""
    result = await governance_tools.governance_get_rls("table_data")
    assert len(result) == 1
    assert result[0].type == "text"
    mock_api_client.get.assert_called_once_with("/api/v1/rls/table_data")


@pytest.mark.asyncio
async def test_governance_health_check_error(mock_api_client: MagicMock) -> None:
    """Test health check with error response."""
    mock_api_client.get.return_value.status_code = 503
    result = await governance_tools.governance_health_check()
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert "error" in data or data.get("status") != "ok"


@pytest.mark.asyncio
async def test_governance_get_policy_exception(mock_api_client: MagicMock) -> None:
    """Test get policy with exception."""
    mock_api_client.get.side_effect = Exception("Policy service unavailable")
    result = await governance_tools.governance_get_policy("policy123")
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["error"] == "InternalError"


@pytest.mark.asyncio
async def test_governance_check_access_error(mock_api_client: MagicMock) -> None:
    """Test check access with 403 Forbidden."""
    mock_api_client.post.return_value.status_code = 403
    result = await governance_tools.governance_check_access("user123", "read", "resource123")
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert "error" in data or "denied" in str(data).lower()


@pytest.mark.asyncio
async def test_governance_list_permissions_exception(mock_api_client: MagicMock) -> None:
    """Test list permissions with exception."""
    mock_api_client.get.side_effect = Exception("Service timeout")
    result = await governance_tools.governance_list_permissions()
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["error"] == "InternalError"


@pytest.mark.asyncio
async def test_governance_update_rls_exception(mock_api_client: MagicMock) -> None:
    """Test update RLS with exception."""
    mock_api_client.post.side_effect = Exception("RLS update failed")
    result = await governance_tools.governance_update_rls("table", [])
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["error"] == "InternalError"


@pytest.mark.asyncio
async def test_governance_list_policies_exception(mock_api_client: MagicMock) -> None:
    """Test list policies with exception."""
    mock_api_client.get.side_effect = Exception("Policy database down")
    result = await governance_tools.governance_list_policies()
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["error"] == "InternalError"


@pytest.mark.asyncio
async def test_governance_list_policies_error(mock_api_client: MagicMock) -> None:
    """Test list policies with 500 error."""
    mock_api_client.get.return_value.status_code = 500
    result = await governance_tools.governance_list_policies()
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert "error" in data or data.get("status") == "error"


@pytest.mark.asyncio
async def test_governance_get_user_permissions_exception(mock_api_client: MagicMock) -> None:
    """Test get user permissions with exception."""
    mock_api_client.get.side_effect = Exception("Permission service down")
    result = await governance_tools.governance_get_user_permissions("user-123")
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["error"] == "InternalError"


@pytest.mark.asyncio
async def test_governance_get_user_permissions_error(mock_api_client: MagicMock) -> None:
    """Test get user permissions with 404 Not Found."""
    mock_api_client.get.return_value.status_code = 404
    result = await governance_tools.governance_get_user_permissions("nonexistent")
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert "error" in data or "not found" in str(data).lower()


@pytest.mark.asyncio
async def test_governance_get_rls_exception(mock_api_client: MagicMock) -> None:
    """Test get RLS with exception."""
    mock_api_client.get.side_effect = Exception("RLS service unavailable")
    result = await governance_tools.governance_get_rls("table_data")
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["error"] == "InternalError"


@pytest.mark.asyncio
async def test_governance_get_rls_404(mock_api_client: MagicMock) -> None:
    """Test get RLS with 404 Not Found."""
    mock_api_client.get.return_value.status_code = 404
    result = await governance_tools.governance_get_rls("nonexistent_table")
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert "error" in data or "not found" in str(data).lower()


@pytest.mark.asyncio
async def test_governance_get_policy_404(mock_api_client: MagicMock) -> None:
    """Test get policy with 404 Not Found."""
    mock_api_client.get.return_value.status_code = 404
    result = await governance_tools.governance_get_policy("nonexistent-policy")
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert "error" in data or "not found" in str(data).lower()


@pytest.mark.asyncio
async def test_governance_update_rls_error(mock_api_client: MagicMock) -> None:
    """Test update RLS with 400 Bad Request."""
    mock_api_client.post.return_value.status_code = 400
    result = await governance_tools.governance_update_rls("table", {"invalid": "rules"})
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert "error" in data
