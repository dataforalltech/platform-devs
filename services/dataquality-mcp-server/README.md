# dataquality-mcp — Data Quality Validation, Anomaly Detection & Rule Management

MCP Server for platform-dataquality. Exposes data quality operations as standardized tools.

## Features

- **Validation Rules** — Create and manage data quality validation rules
- **Data Validation** — Execute validation against datasets
- **Anomaly Detection** — Detect data drift and anomalies
- **Quality Metrics** — Compute quality metrics and statistics
- **Rule Management** — CRUD operations on validation rules

## Tools

### dataquality_list_rules
List all validation rules.
- No inputs required
- Returns: list of validation rules with configuration

### dataquality_create_rule
Create new validation rule.
- Inputs: `dataset_id`, `rule_name`, `rule_type` (null_check|range_check|pattern|etc), `config`
- Returns: created rule ID and metadata

### dataquality_run_validation
Execute validation against dataset.
- Inputs: `dataset_id`, optional `rule_ids` (specific rules to execute)
- Returns: validation results (passed|failed) for each rule

### dataquality_get_anomalies
Detect and list data anomalies.
- Inputs: `dataset_id`, optional `anomaly_type` (outlier|drift), `limit` (default: 100)
- Returns: list of detected anomalies with severity and details

### dataquality_get_metrics
Get quality metrics and statistics for dataset.
- Inputs: `dataset_id`, optional `metric_type` (completeness|accuracy|consistency)
- Returns: quality metrics with historical trends

### dataquality_validate_dataset
Perform full dataset validation including rules and anomalies.
- Inputs: `dataset_id`, optional `include_anomalies` (default: false)
- Returns: comprehensive validation report

### dataquality_get_rule
Get validation rule details.
- Inputs: `rule_id`
- Returns: rule configuration and execution history

### dataquality_delete_rule
Delete validation rule.
- Inputs: `rule_id`
- Returns: deletion confirmation

## Installation

```bash
pip install -e .
```

## Configuration

Environment variables (prefix: `MCP_DATAQUALITY_`):

- `MCP_DATAQUALITY_BASE_URL` — platform-dataquality API endpoint (default: `http://localhost:8008/api/v1`)
- `MCP_DATAQUALITY_API_KEY` — Authentication token
- `MCP_DATAQUALITY_TIMEOUT_SECONDS` — HTTP timeout (default: 60)

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
