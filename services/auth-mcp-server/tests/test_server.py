"""Tests for MCP server."""

import pytest

from src.server import mcp_server


@pytest.mark.asyncio
async def test_list_tools() -> None:
    """Test that list_tools returns all expected tools."""
    tools = await mcp_server.list_tools()

    assert len(tools) == 10
    tool_names = {tool.name for tool in tools}

    expected_names = {
        "auth_health_check",
        "auth_check_email",
        "auth_list_tenants",
        "auth_login",
        "auth_get_me",
        "auth_get_permissions",
        "auth_refresh_token",
        "auth_logout",
        "auth_get_service_token",
        "auth_validate_token",
    }

    assert tool_names == expected_names


@pytest.mark.asyncio
async def test_call_tool_not_found() -> None:
    """Test calling a tool that doesn't exist."""
    result = await mcp_server.call_tool("nonexistent_tool", {})

    assert len(result) == 1
    assert "ToolNotFound" in result[0].text
