# monitor-mcp — Service Monitoring, Alerts & Health Checks

MCP Server for platform-monitor. Exposes service monitoring and alerting operations as standardized tools.

## Features

- **Service Status** — Real-time service health monitoring
- **Metrics Collection** — CPU, memory, latency, and throughput metrics
- **Alert Management** — Create, list, and acknowledge alerts
- **Health Checks** — Periodic service health validation

## Tools

### monitor_get_service_status
Get service health status.
- Inputs: `service_name`
- Returns: current status, last check time, health details

### monitor_list_services
List all monitored services.
- No inputs required
- Returns: list of services with current status

### monitor_get_metrics
Get service metrics (cpu, memory, latency, throughput).
- Inputs: `service_name`, optional `metric_type` (cpu|memory|latency|throughput)
- Returns: metric values and time series data

### monitor_list_alerts
List all active alerts.
- No inputs required
- Returns: list of active alerts with severity and timestamp

### monitor_get_alert
Get alert details.
- Inputs: `alert_id`
- Returns: alert configuration, severity, history

### monitor_acknowledge_alert
Acknowledge alert.
- Inputs: `alert_id`
- Returns: acknowledgment confirmation and timestamp

## Installation

```bash
pip install -e .
```

## Configuration

Environment variables (prefix: `MCP_MONITOR_`):

- `MCP_MONITOR_BASE_URL` — platform-monitor API endpoint (default: `http://localhost:8007/api/v1`)
- `MCP_MONITOR_API_KEY` — Authentication token
- `MCP_MONITOR_TIMEOUT_SECONDS` — HTTP timeout (default: 30)

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
