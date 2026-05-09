"""Tests for MCP server implementation."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_list_tools() -> None:
    """Test listing available tools."""
    from src.server.mcp_server import list_tools

    tools = await list_tools()

    assert len(tools) == 8
    tool_names = [tool.name for tool in tools]
    assert "cache_health_check" in tool_names
    assert "cache_set" in tool_names
    assert "cache_get" in tool_names
    assert "cache_delete" in tool_names
    assert "cache_clear_all" in tool_names
    assert "cache_get_stats" in tool_names
    assert "cache_set_pattern" in tool_names
    assert "cache_increment" in tool_names


@pytest.mark.asyncio
async def test_list_tools_descriptions() -> None:
    """Test that tools have descriptions."""
    from src.server.mcp_server import list_tools

    tools = await list_tools()

    for tool in tools:
        assert tool.description is not None
        assert len(tool.description) > 0


@pytest.mark.asyncio
async def test_list_tools_schemas() -> None:
    """Test that tools have input schemas."""
    from src.server.mcp_server import list_tools

    tools = await list_tools()

    for tool in tools:
        assert tool.inputSchema is not None
        assert "type" in tool.inputSchema
        assert "properties" in tool.inputSchema


@pytest.mark.asyncio
async def test_call_tool_health_check(mock_api_client: MagicMock) -> None:
    """Test calling cache_health_check tool."""
    from src.server.mcp_server import call_tool

    mock_api_client.get.return_value.status_code = 200
    mock_api_client.get.return_value.json.return_value = {"status": "healthy"}

    result = await call_tool("cache_health_check", {})

    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["status"] == "ok"


@pytest.mark.asyncio
async def test_call_tool_cache_set(mock_api_client: MagicMock) -> None:
    """Test calling cache_set tool."""
    from src.server.mcp_server import call_tool

    mock_api_client.post.return_value.status_code = 200
    mock_api_client.post.return_value.json.return_value = {"status": "set"}

    result = await call_tool("cache_set", {"key": "test", "value": "data"})

    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["status"] == "set"


@pytest.mark.asyncio
async def test_call_tool_cache_set_with_ttl(mock_api_client: MagicMock) -> None:
    """Test calling cache_set tool with TTL."""
    from src.server.mcp_server import call_tool

    mock_api_client.post.return_value.status_code = 200
    mock_api_client.post.return_value.json.return_value = {"ttl": 3600}

    result = await call_tool("cache_set", {"key": "test", "value": "data", "ttl": 3600})

    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["ttl"] == 3600


@pytest.mark.asyncio
async def test_call_tool_cache_get(mock_api_client: MagicMock) -> None:
    """Test calling cache_get tool."""
    from src.server.mcp_server import call_tool

    mock_api_client.get.return_value.status_code = 200
    mock_api_client.get.return_value.json.return_value = {"value": "cached_data"}

    result = await call_tool("cache_get", {"key": "test"})

    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["value"] == "cached_data"


@pytest.mark.asyncio
async def test_call_tool_cache_delete(mock_api_client: MagicMock) -> None:
    """Test calling cache_delete tool."""
    from src.server.mcp_server import call_tool

    mock_api_client.delete.return_value.status_code = 200
    mock_api_client.delete.return_value.json.return_value = {"deleted": True}

    result = await call_tool("cache_delete", {"key": "test"})

    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["deleted"] is True


@pytest.mark.asyncio
async def test_call_tool_cache_clear_all(mock_api_client: MagicMock) -> None:
    """Test calling cache_clear_all tool."""
    from src.server.mcp_server import call_tool

    mock_api_client.delete.return_value.status_code = 200
    mock_api_client.delete.return_value.json.return_value = {"cleared": True}

    result = await call_tool("cache_clear_all", {})

    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["cleared"] is True


@pytest.mark.asyncio
async def test_call_tool_cache_get_stats(mock_api_client: MagicMock) -> None:
    """Test calling cache_get_stats tool."""
    from src.server.mcp_server import call_tool

    mock_api_client.get.return_value.status_code = 200
    mock_api_client.get.return_value.json.return_value = {"hits": 1000, "misses": 100}

    result = await call_tool("cache_get_stats", {})

    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["hits"] == 1000


@pytest.mark.asyncio
async def test_call_tool_cache_set_pattern(mock_api_client: MagicMock) -> None:
    """Test calling cache_set_pattern tool."""
    from src.server.mcp_server import call_tool

    mock_api_client.post.return_value.status_code = 200
    mock_api_client.post.return_value.json.return_value = {"set_count": 3}

    result = await call_tool(
        "cache_set_pattern",
        {"pattern": "user:*", "values": {"a": "1", "b": "2", "c": "3"}},
    )

    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["set_count"] == 3


@pytest.mark.asyncio
async def test_call_tool_cache_increment(mock_api_client: MagicMock) -> None:
    """Test calling cache_increment tool."""
    from src.server.mcp_server import call_tool

    mock_api_client.put.return_value.status_code = 200
    mock_api_client.put.return_value.json.return_value = {"value": 5}

    result = await call_tool("cache_increment", {"key": "counter", "amount": 5})

    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["value"] == 5


@pytest.mark.asyncio
async def test_call_tool_unknown_tool(mock_api_client: MagicMock) -> None:
    """Test calling unknown tool."""
    from src.server.mcp_server import call_tool

    result = await call_tool("unknown_tool", {})

    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["error"] == "UnknownTool"
    assert "unknown_tool" in data["details"]


@pytest.mark.asyncio
async def test_call_tool_with_exception(mock_api_client: MagicMock) -> None:
    """Test tool call with exception."""
    from src.server.mcp_server import call_tool

    mock_api_client.get.side_effect = Exception("Connection failed")

    result = await call_tool("cache_health_check", {})

    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["error"] == "InternalError"


def test_server_instance() -> None:
    """Test that server instance is created."""
    from src.server.mcp_server import server

    assert server is not None
    assert server.name == "cache-mcp"


def test_settings_instance() -> None:
    """Test that settings instance is created."""
    from src.server.mcp_server import settings

    assert settings is not None
    assert settings.base_url == "http://localhost:8025"
