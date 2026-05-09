"""Tests for pipeline tools."""

import json
import pytest
from unittest.mock import AsyncMock, patch

from src.tools.pipeline_tools import (
    pipeline_cancel_run,
    pipeline_create_pipeline,
    pipeline_delete_pipeline,
    pipeline_get_pipeline,
    pipeline_get_pipeline_logs,
    pipeline_get_run_history,
    pipeline_get_run_status,
    pipeline_list_pipelines,
    pipeline_trigger_run,
)


@pytest.mark.asyncio
async def test_pipeline_create_pipeline_success():
    """Test successful pipeline creation."""
    with patch("src.tools.pipeline_tools.httpx.AsyncClient") as mock_client_class:
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"pipeline_id": "pipe-123", "name": "test_pipeline"}
        mock_response.raise_for_status = AsyncMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__.return_value = mock_client

        mock_client_class.return_value = mock_client

        result = await pipeline_create_pipeline("test_pipeline", {"steps": []})
        data = json.loads(result)

        assert data["status"] == "ok"
        assert data["data"]["pipeline_id"] == "pipe-123"


@pytest.mark.asyncio
async def test_pipeline_create_pipeline_exception():
    """Test pipeline creation with exception."""
    with patch("src.tools.pipeline_tools.httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=Exception("Connection failed"))
        mock_client.__aenter__.return_value = mock_client

        mock_client_class.return_value = mock_client

        result = await pipeline_create_pipeline("test_pipeline", {"steps": []})
        data = json.loads(result)

        assert data["error"] == "Exception"
        assert "Connection failed" in data["details"]


@pytest.mark.asyncio
async def test_pipeline_get_pipeline_success():
    """Test successful pipeline retrieval."""
    with patch("src.tools.pipeline_tools.httpx.AsyncClient") as mock_client_class:
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"pipeline_id": "pipe-123", "name": "test_pipeline"}
        mock_response.raise_for_status = AsyncMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__.return_value = mock_client

        mock_client_class.return_value = mock_client

        result = await pipeline_get_pipeline("pipe-123")
        data = json.loads(result)

        assert data["status"] == "ok"
        assert data["data"]["pipeline_id"] == "pipe-123"


@pytest.mark.asyncio
async def test_pipeline_get_pipeline_not_found():
    """Test pipeline retrieval with not found error."""
    with patch("src.tools.pipeline_tools.httpx.AsyncClient") as mock_client_class:
        mock_response = AsyncMock()
        mock_response.status_code = 404

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__.return_value = mock_client

        mock_client_class.return_value = mock_client

        result = await pipeline_get_pipeline("nonexistent")
        data = json.loads(result)

        assert data["error"] == "NotFound"
        assert "not found" in data["details"].lower()


@pytest.mark.asyncio
async def test_pipeline_list_pipelines_success():
    """Test successful pipeline listing."""
    with patch("src.tools.pipeline_tools.httpx.AsyncClient") as mock_client_class:
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {"pipeline_id": "pipe-1", "name": "pipeline1"},
            {"pipeline_id": "pipe-2", "name": "pipeline2"},
        ]
        mock_response.raise_for_status = AsyncMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__.return_value = mock_client

        mock_client_class.return_value = mock_client

        result = await pipeline_list_pipelines()
        data = json.loads(result)

        assert data["status"] == "ok"
        assert len(data["data"]) == 2


@pytest.mark.asyncio
async def test_pipeline_trigger_run_success():
    """Test successful pipeline run trigger."""
    with patch("src.tools.pipeline_tools.httpx.AsyncClient") as mock_client_class:
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"run_id": "run-123", "status": "queued"}
        mock_response.raise_for_status = AsyncMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__.return_value = mock_client

        mock_client_class.return_value = mock_client

        result = await pipeline_trigger_run("pipe-123", {"param": "value"})
        data = json.loads(result)

        assert data["status"] == "ok"
        assert data["data"]["run_id"] == "run-123"


@pytest.mark.asyncio
async def test_pipeline_get_run_status_success():
    """Test successful run status retrieval."""
    with patch("src.tools.pipeline_tools.httpx.AsyncClient") as mock_client_class:
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"run_id": "run-123", "status": "running", "progress": 45}
        mock_response.raise_for_status = AsyncMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__.return_value = mock_client

        mock_client_class.return_value = mock_client

        result = await pipeline_get_run_status("run-123")
        data = json.loads(result)

        assert data["status"] == "ok"
        assert data["data"]["status"] == "running"


@pytest.mark.asyncio
async def test_pipeline_get_pipeline_logs_success():
    """Test successful log retrieval."""
    with patch("src.tools.pipeline_tools.httpx.AsyncClient") as mock_client_class:
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "logs": [
                {"timestamp": "2026-05-09T10:00:00Z", "level": "INFO", "message": "Started"}
            ]
        }
        mock_response.raise_for_status = AsyncMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__.return_value = mock_client

        mock_client_class.return_value = mock_client

        result = await pipeline_get_pipeline_logs("pipe-123")
        data = json.loads(result)

        assert data["status"] == "ok"
        assert len(data["data"]["logs"]) > 0


@pytest.mark.asyncio
async def test_pipeline_cancel_run_success():
    """Test successful run cancellation."""
    with patch("src.tools.pipeline_tools.httpx.AsyncClient") as mock_client_class:
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"run_id": "run-123", "status": "cancelled"}
        mock_response.raise_for_status = AsyncMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__.return_value = mock_client

        mock_client_class.return_value = mock_client

        result = await pipeline_cancel_run("run-123")
        data = json.loads(result)

        assert data["status"] == "ok"
        assert data["data"]["status"] == "cancelled"


@pytest.mark.asyncio
async def test_pipeline_delete_pipeline_success():
    """Test successful pipeline deletion."""
    with patch("src.tools.pipeline_tools.httpx.AsyncClient") as mock_client_class:
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"pipeline_id": "pipe-123", "deleted": True}
        mock_response.raise_for_status = AsyncMock()

        mock_client = AsyncMock()
        mock_client.delete = AsyncMock(return_value=mock_response)
        mock_client.__aenter__.return_value = mock_client

        mock_client_class.return_value = mock_client

        result = await pipeline_delete_pipeline("pipe-123")
        data = json.loads(result)

        assert data["status"] == "ok"


@pytest.mark.asyncio
async def test_pipeline_get_run_history_success():
    """Test successful history retrieval."""
    with patch("src.tools.pipeline_tools.httpx.AsyncClient") as mock_client_class:
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "runs": [
                {"run_id": "run-1", "status": "completed"},
                {"run_id": "run-2", "status": "running"},
            ]
        }
        mock_response.raise_for_status = AsyncMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__.return_value = mock_client

        mock_client_class.return_value = mock_client

        result = await pipeline_get_run_history("pipe-123", limit=20)
        data = json.loads(result)

        assert data["status"] == "ok"
