"""Tests for MCP server."""

import json
from unittest.mock import MagicMock

import pytest

from src.server import mcp_server


@pytest.mark.asyncio
async def test_list_tools() -> None:
    """Test that list_tools returns all expected tools."""
    tools = await mcp_server.list_tools()

    assert len(tools) == 8
    tool_names = {tool.name for tool in tools}

    expected_names = {
        "connectors_health_check",
        "connectors_list",
        "connectors_get",
        "connectors_search",
        "connectors_get_schema",
        "connectors_test_connection",
        "connectors_list_credentials",
        "connectors_get_credential",
    }

    assert tool_names == expected_names


@pytest.mark.asyncio
async def test_call_tool_not_found() -> None:
    """Test calling a tool that doesn't exist."""
    result = await mcp_server.call_tool("nonexistent_tool", {})

    assert len(result) == 1
    assert "ToolNotFound" in result[0].text


@pytest.mark.asyncio
async def test_call_tool_health_check(mock_api_client: MagicMock) -> None:
    """Test calling health check through server."""
    result = await mcp_server.call_tool("connectors_health_check", {})
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["status"] == "ok"


@pytest.mark.asyncio
async def test_call_tool_list(mock_api_client: MagicMock) -> None:
    """Test calling list through server."""
    result = await mcp_server.call_tool("connectors_list", {})
    assert len(result) == 1
    assert result[0].type == "text"


@pytest.mark.asyncio
async def test_call_tool_get(mock_api_client: MagicMock) -> None:
    """Test calling get through server."""
    result = await mcp_server.call_tool("connectors_get", {"connector_name": "salesforce"})
    assert len(result) == 1
    assert result[0].type == "text"


@pytest.mark.asyncio
async def test_call_tool_search(mock_api_client: MagicMock) -> None:
    """Test calling search through server."""
    result = await mcp_server.call_tool("connectors_search", {"query": "salesforce"})
    assert len(result) == 1
    assert result[0].type == "text"


@pytest.mark.asyncio
async def test_call_tool_get_schema(mock_api_client: MagicMock) -> None:
    """Test calling get_schema through server."""
    result = await mcp_server.call_tool("connectors_get_schema", {"connector_name": "salesforce"})
    assert len(result) == 1
    assert result[0].type == "text"


@pytest.mark.asyncio
async def test_call_tool_list_credentials(mock_api_client: MagicMock) -> None:
    """Test calling list_credentials through server."""
    result = await mcp_server.call_tool("connectors_list_credentials", {})
    assert len(result) == 1
    assert result[0].type == "text"
