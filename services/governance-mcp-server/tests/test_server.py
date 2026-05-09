"""Tests for MCP server."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.server.mcp_server import call_tool, list_tools


@pytest.mark.asyncio
async def test_list_tools() -> None:
    """Test list_tools returns all governance tools."""
    tools = await list_tools()
    assert len(tools) == 8
    tool_names = [t.name for t in tools]
    assert "governance_health_check" in tool_names
    assert "governance_get_policy" in tool_names
    assert "governance_list_policies" in tool_names
    assert "governance_check_access" in tool_names
    assert "governance_list_permissions" in tool_names
    assert "governance_get_user_permissions" in tool_names
    assert "governance_update_rls" in tool_names
    assert "governance_get_rls" in tool_names


@pytest.mark.asyncio
async def test_call_tool_health_check(mock_api_client: MagicMock) -> None:
    """Test calling health check tool."""
    result = await call_tool("governance_health_check", {})
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["status"] == "ok"


@pytest.mark.asyncio
async def test_call_tool_get_policy(mock_api_client: MagicMock) -> None:
    """Test calling get policy tool."""
    result = await call_tool("governance_get_policy", {"policy_id": "policy-123"})
    assert len(result) == 1
    assert result[0].type == "text"


@pytest.mark.asyncio
async def test_call_tool_not_found() -> None:
    """Test calling non-existent tool."""
    result = await call_tool("governance_nonexistent", {})
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["error"] == "ToolNotFound"
    assert "governance_nonexistent" in data["details"]


@pytest.mark.asyncio
async def test_call_tool_with_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test tool call with exception handling."""
    # Mock the governance tool to raise an exception
    async def mock_health_check() -> None:
        raise ValueError("Test error")

    monkeypatch.setattr("src.server.mcp_server.governance_tools.governance_health_check", mock_health_check)

    result = await call_tool("governance_health_check", {})
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["error"] == "InternalError"


@pytest.mark.asyncio
async def test_call_tool_list_policies(mock_api_client: MagicMock) -> None:
    """Test calling list policies tool."""
    result = await call_tool("governance_list_policies", {})
    assert len(result) == 1
    assert result[0].type == "text"


@pytest.mark.asyncio
async def test_call_tool_check_access(mock_api_client: MagicMock) -> None:
    """Test calling check access tool."""
    result = await call_tool("governance_check_access", {
        "user_id": "user-123",
        "resource": "resource-456",
        "action": "read",
    })
    assert len(result) == 1
    assert result[0].type == "text"


@pytest.mark.asyncio
async def test_call_tool_list_permissions(mock_api_client: MagicMock) -> None:
    """Test calling list permissions tool."""
    result = await call_tool("governance_list_permissions", {})
    assert len(result) == 1
    assert result[0].type == "text"


@pytest.mark.asyncio
async def test_call_tool_get_user_permissions(mock_api_client: MagicMock) -> None:
    """Test calling get user permissions tool."""
    result = await call_tool("governance_get_user_permissions", {"user_id": "user-123"})
    assert len(result) == 1
    assert result[0].type == "text"
