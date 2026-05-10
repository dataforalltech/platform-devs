# pipeline-mcp — Pipeline Orchestration & Execution

MCP Server for platform-pipeline. Exposes pipeline operations as standardized tools for orchestration, execution, and monitoring.

## Features

- **Pipeline Management** — CRUD operations on pipelines
- **Execution Control** — Trigger, monitor, and cancel pipeline runs
- **Logging** — Access pipeline execution logs
- **History** — View execution history and run status

## Tools

### pipeline_create_pipeline
Create new pipeline.
- Inputs: `name`, `config` (object with pipeline configuration)
- Returns: created pipeline ID, metadata, and status

### pipeline_get_pipeline
Get pipeline details and metadata.
- Inputs: `pipeline_id`
- Returns: pipeline information, configuration, creation date

### pipeline_list_pipelines
List all pipelines.
- No inputs required
- Returns: list of pipelines with metadata

### pipeline_trigger_run
Trigger pipeline execution.
- Inputs: `pipeline_id`, optional `inputs` (dict with execution parameters)
- Returns: run ID and initial status

### pipeline_get_run_status
Get pipeline run status.
- Inputs: `run_id`
- Returns: run status (queued|running|completed|failed), progress, metrics

### pipeline_get_pipeline_logs
Get pipeline execution logs.
- Inputs: `pipeline_id`, optional `run_id` (specific run or latest)
- Returns: log entries with timestamps and levels

### pipeline_cancel_run
Cancel pipeline run.
- Inputs: `run_id`
- Returns: cancellation confirmation and final status

### pipeline_delete_pipeline
Delete pipeline.
- Inputs: `pipeline_id`
- Returns: deletion confirmation

### pipeline_get_run_history
Get execution history for pipeline.
- Inputs: `pipeline_id`, optional `limit` (default: 20)
- Returns: list of recent runs with status and timestamps

## Installation

```bash
pip install -e .
```

## Configuration

Environment variables (prefix: `MCP_PIPELINE_`):

- `MCP_PIPELINE_BASE_URL` — platform-pipeline API endpoint (default: `http://localhost:8003/api/v1`)
- `MCP_PIPELINE_API_KEY` — Authentication token
- `MCP_PIPELINE_TIMEOUT_SECONDS` — HTTP timeout (default: 120)

## Running

```bash
python -m src.server.mcp_server
```

## Testing

```bash
pytest tests/ -v --cov=src
```

## Error Handling

All tools return JSON responses:

**Success:**
```json
{"status": "ok", "data": {...}}
```

**Error:**
```json
{"error": "ErrorType", "details": "error message"}
```

Error types: `NotFound`, `BadRequest`, `HTTPError`, `Exception`

## Related

- platform-pipeline API documentation
- DAI Orchestrator (Fase 4)
