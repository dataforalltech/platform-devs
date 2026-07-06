# Scheduler MCP

MCP server exposing scheduler tools (job management, scheduling).

## Quick Start

```bash
pip install -e ".[dev]"
pytest tests/ -v
python3 -m src.server.mcp_server
```

## Tools

1. scheduler_health_check - Check service health
2. scheduler_list_jobs - List all scheduled jobs
3. scheduler_get_job - Get job by ID
4. scheduler_create_job - Create new job
5. scheduler_update_job - Update job
6. scheduler_delete_job - Delete job
7. scheduler_trigger_job - Trigger job manually

## Testing

```bash
pytest tests/ --cov=src --cov-report=html
```

## Configuration

Set environment variables:
- `MCP_SCHEDULER_BASE_URL` - Base URL of Scheduler service (default: http://localhost:8005 local / http://localhost:8000 Docker)
- `MCP_SCHEDULER_INTERNAL_TOKEN` - Internal authentication token (required)
- `MCP_SCHEDULER_TIMEOUT` - Request timeout in seconds (default: 30.0)
- `MCP_SCHEDULER_LOG_LEVEL` - Log level (default: INFO)
