"""Tests for MCP server functionality."""

import json
from unittest.mock import MagicMock

import pytest

from src.server.mcp_server import call_tool, list_tools


@pytest.mark.asyncio
async def test_list_tools() -> None:
    """Test that all tools are listed correctly."""
    tools = await list_tools()
    assert len(tools) == 8
    tool_names = {tool.name for tool in tools}
    expected_names = {
        "scheduler_health_check",
        "scheduler_list_tasks",
        "scheduler_get_task",
        "scheduler_create_task",
        "scheduler_update_task",
        "scheduler_run_task",
        "scheduler_get_task_history",
        "scheduler_list_schedules",
    }
    assert tool_names == expected_names


@pytest.mark.asyncio
async def test_health_check_tool_schema() -> None:
    """Test health check tool schema."""
    tools = await list_tools()
    health_tool = next(t for t in tools if t.name == "scheduler_health_check")
    assert health_tool.description == "Check if platform-scheduler service is healthy"
    assert health_tool.inputSchema["required"] == []


@pytest.mark.asyncio
async def test_create_task_tool_schema() -> None:
    """Test create task tool schema."""
    tools = await list_tools()
    create_tool = next(t for t in tools if t.name == "scheduler_create_task")
    assert create_tool.description == "Create a new scheduler task with cron expression"
    required_props = set(create_tool.inputSchema["required"])
    assert required_props == {"cron_expression", "command", "tenant_id"}


@pytest.mark.asyncio
async def test_call_tool_health_check(mock_api_client: MagicMock) -> None:
    """Test calling health check through server."""
    result = await call_tool("scheduler_health_check", {})
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["status"] == "ok"


@pytest.mark.asyncio
async def test_call_tool_list_tasks(mock_api_client: MagicMock) -> None:
    """Test calling list tasks through server."""
    result = await call_tool("scheduler_list_tasks", {})
    assert len(result) == 1
    assert result[0].type == "text"


@pytest.mark.asyncio
async def test_call_tool_get_task(mock_api_client: MagicMock) -> None:
    """Test calling get task through server."""
    result = await call_tool("scheduler_get_task", {"task_id": "task123"})
    assert len(result) == 1
    assert result[0].type == "text"


@pytest.mark.asyncio
async def test_call_tool_run_task(mock_api_client: MagicMock) -> None:
    """Test calling run task through server."""
    result = await call_tool("scheduler_run_task", {"task_id": "task123"})
    assert len(result) == 1
    assert result[0].type == "text"


@pytest.mark.asyncio
async def test_call_tool_get_task_history(mock_api_client: MagicMock) -> None:
    """Test calling get task history through server."""
    result = await call_tool("scheduler_get_task_history", {"task_id": "task123"})
    assert len(result) == 1
    assert result[0].type == "text"


@pytest.mark.asyncio
async def test_call_tool_list_schedules(mock_api_client: MagicMock) -> None:
    """Test calling list schedules through server."""
    result = await call_tool("scheduler_list_schedules", {})
    assert len(result) == 1
    assert result[0].type == "text"


@pytest.mark.asyncio
async def test_call_tool_nonexistent() -> None:
    """Test calling a tool that doesn't exist."""
    result = await call_tool("nonexistent_tool", {})
    assert len(result) == 1
    assert "ToolNotFound" in result[0].text
