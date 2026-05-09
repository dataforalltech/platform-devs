"""Tests for scheduler tools."""

import json
from unittest.mock import MagicMock

import pytest

from src.tools import scheduler_tools


@pytest.mark.asyncio
async def test_scheduler_health_check(mock_api_client: MagicMock) -> None:
    """Test health check tool."""
    result = await scheduler_tools.scheduler_health_check()
    assert len(result) == 1
    assert result[0].type == "text"
    data = json.loads(result[0].text)
    assert data["status"] == "ok"
    mock_api_client.get.assert_called_once_with("/api/health")


@pytest.mark.asyncio
async def test_scheduler_list_tasks(mock_api_client: MagicMock) -> None:
    """Test list tasks tool."""
    result = await scheduler_tools.scheduler_list_tasks()
    assert len(result) == 1
    assert result[0].type == "text"
    mock_api_client.get.assert_called_once_with("/api/v1/tasks", params={})


@pytest.mark.asyncio
async def test_scheduler_list_tasks_with_tenant(mock_api_client: MagicMock) -> None:
    """Test list tasks tool with tenant filter."""
    result = await scheduler_tools.scheduler_list_tasks(tenant_id="tenant123")
    assert len(result) == 1
    assert result[0].type == "text"
    mock_api_client.get.assert_called_once_with("/api/v1/tasks", params={"tenant_id": "tenant123"})


@pytest.mark.asyncio
async def test_scheduler_get_task(mock_api_client: MagicMock) -> None:
    """Test get task tool."""
    result = await scheduler_tools.scheduler_get_task("task123")
    assert len(result) == 1
    assert result[0].type == "text"
    mock_api_client.get.assert_called_once_with("/api/v1/tasks/task123")


@pytest.mark.asyncio
async def test_scheduler_get_task_not_found(mock_api_client: MagicMock) -> None:
    """Test get task tool when task not found."""
    mock_api_client.get.return_value.status_code = 404
    result = await scheduler_tools.scheduler_get_task("task123")
    assert len(result) == 1
    assert result[0].type == "text"
    data = json.loads(result[0].text)
    assert data["error"] == "NotFound"


@pytest.mark.asyncio
async def test_scheduler_create_task(mock_api_client: MagicMock) -> None:
    """Test create task tool."""
    result = await scheduler_tools.scheduler_create_task(
        cron_expression="0 0 * * *",
        command="echo hello",
        tenant_id="tenant123",
        name="my task",
    )
    mock_api_client.post.return_value.status_code = 201
    assert len(result) == 1
    assert result[0].type == "text"


@pytest.mark.asyncio
async def test_scheduler_update_task(mock_api_client: MagicMock) -> None:
    """Test update task tool."""
    result = await scheduler_tools.scheduler_update_task(
        task_id="task123",
        cron_expression="0 12 * * *",
    )
    assert len(result) == 1
    assert result[0].type == "text"
    mock_api_client.put.assert_called_once()


@pytest.mark.asyncio
async def test_scheduler_run_task(mock_api_client: MagicMock) -> None:
    """Test run task tool."""
    result = await scheduler_tools.scheduler_run_task("task123")
    assert len(result) == 1
    assert result[0].type == "text"
    mock_api_client.post.assert_called_once_with("/api/v1/tasks/task123/run", json={})


@pytest.mark.asyncio
async def test_scheduler_get_task_history(mock_api_client: MagicMock) -> None:
    """Test get task history tool."""
    result = await scheduler_tools.scheduler_get_task_history("task123")
    assert len(result) == 1
    assert result[0].type == "text"
    mock_api_client.get.assert_called_once_with("/api/v1/tasks/task123/history", params={"limit": 10})


@pytest.mark.asyncio
async def test_scheduler_get_task_history_with_limit(mock_api_client: MagicMock) -> None:
    """Test get task history tool with custom limit."""
    result = await scheduler_tools.scheduler_get_task_history("task123", limit=50)
    assert len(result) == 1
    assert result[0].type == "text"
    mock_api_client.get.assert_called_once_with("/api/v1/tasks/task123/history", params={"limit": 50})


@pytest.mark.asyncio
async def test_scheduler_list_schedules(mock_api_client: MagicMock) -> None:
    """Test list schedules tool."""
    result = await scheduler_tools.scheduler_list_schedules()
    assert len(result) == 1
    assert result[0].type == "text"
    mock_api_client.get.assert_called_once_with("/api/v1/schedules", params={})


@pytest.mark.asyncio
async def test_scheduler_list_schedules_with_tenant(mock_api_client: MagicMock) -> None:
    """Test list schedules tool with tenant filter."""
    result = await scheduler_tools.scheduler_list_schedules(tenant_id="tenant123")
    assert len(result) == 1
    assert result[0].type == "text"
    mock_api_client.get.assert_called_once_with("/api/v1/schedules", params={"tenant_id": "tenant123"})


@pytest.mark.asyncio
async def test_scheduler_health_check_error(mock_api_client: MagicMock) -> None:
    """Test health check with error response."""
    mock_api_client.get.return_value.status_code = 500
    result = await scheduler_tools.scheduler_health_check()
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert "error" in data or data.get("status") != "ok"


@pytest.mark.asyncio
async def test_scheduler_list_tasks_exception(mock_api_client: MagicMock) -> None:
    """Test list tasks with exception."""
    mock_api_client.get.side_effect = Exception("Database connection failed")
    result = await scheduler_tools.scheduler_list_tasks()
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["error"] == "InternalError"


@pytest.mark.asyncio
async def test_scheduler_create_task_error(mock_api_client: MagicMock) -> None:
    """Test create task with validation error."""
    mock_api_client.post.return_value.status_code = 400
    result = await scheduler_tools.scheduler_create_task("task", "* * * * *", "")
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert "error" in data


@pytest.mark.asyncio
async def test_scheduler_run_task_exception(mock_api_client: MagicMock) -> None:
    """Test run task with exception."""
    mock_api_client.post.side_effect = Exception("Task execution failed")
    result = await scheduler_tools.scheduler_run_task("task123")
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["error"] == "InternalError"


@pytest.mark.asyncio
async def test_scheduler_get_task_history_error(mock_api_client: MagicMock) -> None:
    """Test get task history with 404 Not Found."""
    mock_api_client.get.return_value.status_code = 404
    result = await scheduler_tools.scheduler_get_task_history("nonexistent_task")
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert "error" in data or "not found" in str(data).lower()


@pytest.mark.asyncio
async def test_scheduler_update_task_error(mock_api_client: MagicMock) -> None:
    """Test update task with 400 Bad Request."""
    mock_api_client.put.return_value.status_code = 400
    result = await scheduler_tools.scheduler_update_task("task123", "invalid cron")
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert "error" in data


@pytest.mark.asyncio
async def test_scheduler_update_task_exception(mock_api_client: MagicMock) -> None:
    """Test update task with exception."""
    mock_api_client.put.side_effect = Exception("Update service unavailable")
    result = await scheduler_tools.scheduler_update_task("task123", "0 * * * *")
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["error"] == "InternalError"


@pytest.mark.asyncio
async def test_scheduler_update_task_not_found(mock_api_client: MagicMock) -> None:
    """Test update task with 404 Not Found."""
    mock_api_client.put.return_value.status_code = 404
    result = await scheduler_tools.scheduler_update_task("nonexistent", "0 * * * *")
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert "error" in data


@pytest.mark.asyncio
async def test_scheduler_list_schedules_error(mock_api_client: MagicMock) -> None:
    """Test list schedules with 500 error."""
    mock_api_client.get.return_value.status_code = 500
    result = await scheduler_tools.scheduler_list_schedules()
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert "error" in data or data.get("status") == "error"


@pytest.mark.asyncio
async def test_scheduler_list_schedules_exception(mock_api_client: MagicMock) -> None:
    """Test list schedules with exception."""
    mock_api_client.get.side_effect = Exception("Schedule service down")
    result = await scheduler_tools.scheduler_list_schedules()
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["error"] == "InternalError"


@pytest.mark.asyncio
async def test_scheduler_get_task_error(mock_api_client: MagicMock) -> None:
    """Test get task with 500 error."""
    mock_api_client.get.return_value.status_code = 500
    result = await scheduler_tools.scheduler_get_task("task123")
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert "error" in data


@pytest.mark.asyncio
async def test_scheduler_get_task_exception(mock_api_client: MagicMock) -> None:
    """Test get task with exception."""
    mock_api_client.get.side_effect = Exception("Task service error")
    result = await scheduler_tools.scheduler_get_task("task123")
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["error"] == "InternalError"


@pytest.mark.asyncio
async def test_scheduler_create_task_exception(mock_api_client: MagicMock) -> None:
    """Test create task with exception."""
    mock_api_client.post.side_effect = Exception("Create service unavailable")
    result = await scheduler_tools.scheduler_create_task("task", "0 * * * *", "tenant123")
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["error"] == "InternalError"


@pytest.mark.asyncio
async def test_scheduler_run_task_not_found(mock_api_client: MagicMock) -> None:
    """Test run task with 404 Not Found."""
    mock_api_client.post.return_value.status_code = 404
    result = await scheduler_tools.scheduler_run_task("nonexistent")
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert "error" in data or "not found" in str(data).lower()


@pytest.mark.asyncio
async def test_scheduler_list_tasks_500(mock_api_client: MagicMock) -> None:
    """Test list tasks with 500 error."""
    mock_api_client.get.return_value.status_code = 500
    result = await scheduler_tools.scheduler_list_tasks()
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert "error" in data or data.get("status") == "error"
