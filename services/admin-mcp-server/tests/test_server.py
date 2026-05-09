"""Tests for MCP server."""

import json
from unittest.mock import MagicMock

import pytest

from src.server.mcp_server import call_tool, list_tools


@pytest.mark.asyncio
async def test_list_tools() -> None:
    """Test listing available tools."""
    tools = await list_tools()
    assert len(tools) == 9
    tool_names = {tool.name for tool in tools}
    assert tool_names == {
        "admin_health_check",
        "admin_list_users",
        "admin_get_user",
        "admin_create_user",
        "admin_list_domains",
        "admin_list_tenants",
        "admin_get_tenant",
        "admin_assign_role",
        "admin_list_roles",
    }


@pytest.mark.asyncio
async def test_call_tool_health_check(mock_api_client: MagicMock) -> None:
    """Test calling health check tool."""
    result = await call_tool("admin_health_check", {})
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["status"] == "ok"


@pytest.mark.asyncio
async def test_call_tool_list_users(mock_api_client: MagicMock) -> None:
    """Test calling list users tool."""
    mock_api_client.get.return_value.json.return_value = {"users": []}
    result = await call_tool("admin_list_users", {})
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert "users" in data


@pytest.mark.asyncio
async def test_call_tool_get_user(mock_api_client: MagicMock) -> None:
    """Test calling get user tool."""
    mock_api_client.get.return_value.json.return_value = {"id": "user-123"}
    result = await call_tool("admin_get_user", {"user_id": "user-123"})
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["id"] == "user-123"


@pytest.mark.asyncio
async def test_call_tool_not_found() -> None:
    """Test calling non-existent tool."""
    result = await call_tool("nonexistent_tool", {})
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["error"] == "ToolNotFound"


@pytest.mark.asyncio
async def test_tool_schemas() -> None:
    """Test that tool schemas are correct."""
    tools = await list_tools()
    tool_dict = {tool.name: tool for tool in tools}

    # Health check should have no required params
    health = tool_dict["admin_health_check"]
    assert health.inputSchema["required"] == []

    # List users should have no required params
    list_users = tool_dict["admin_list_users"]
    assert list_users.inputSchema["required"] == []

    # Get user should require user_id
    get_user = tool_dict["admin_get_user"]
    assert "user_id" in get_user.inputSchema["required"]

    # Create user should require email and name
    create_user = tool_dict["admin_create_user"]
    assert set(create_user.inputSchema["required"]) == {"email", "name"}

    # Assign role should require user_id and role_id
    assign_role = tool_dict["admin_assign_role"]
    assert set(assign_role.inputSchema["required"]) == {"user_id", "role_id"}
