# analytics-mcp — Dashboards, Reports & BI Operations

MCP Server for platform-analytics. Exposes BI and analytics operations as standardized tools.

## Features

- **Dashboard Management** — CRUD operations on dashboards
- **Report Generation** — Create and execute analytics reports
- **Query Execution** — Run analytics queries with results
- **Report Management** — Manage report lifecycle

## Tools

### analytics_list_dashboards
List all dashboards.
- No inputs required
- Returns: list of dashboards with metadata

### analytics_get_dashboard
Get dashboard details and metadata.
- Inputs: `dashboard_id`
- Returns: dashboard configuration, widgets, metadata

### analytics_create_report
Create new analytics report.
- Inputs: `name`, `query`, optional `dashboard_id`
- Returns: created report ID and metadata

### analytics_execute_query
Execute analytics query.
- Inputs: `query` (SQL or query language)
- Returns: query results and execution metadata

### analytics_list_reports
List all analytics reports.
- No inputs required
- Returns: list of reports with metadata

### analytics_get_report
Get report details.
- Inputs: `report_id`
- Returns: report configuration and metadata

### analytics_delete_report
Delete analytics report.
- Inputs: `report_id`
- Returns: deletion confirmation

## Installation

```bash
pip install -e .
```

## Configuration

Environment variables (prefix: `MCP_ANALYTICS_`):

- `MCP_ANALYTICS_BASE_URL` — platform-analytics API endpoint (default: `http://localhost:8002/api/v1`)
- `MCP_ANALYTICS_API_KEY` — Authentication token
- `MCP_ANALYTICS_TIMEOUT_SECONDS` — HTTP timeout (default: 60)

## Running

```bash
python -m src.server.mcp_server
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
