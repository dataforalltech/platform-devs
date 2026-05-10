# datalake-mcp — Dataset Operations & Schema Discovery

MCP Server for platform-datalake. Exposes dataset operations, schema discovery, and ML data preparation as standardized tools.

## Features

- **Schema Discovery** — List and inspect data schemas
- **Dataset Management** — CRUD operations on datasets
- **ML Preparation** — Train/test split, normalization, feature engineering
- **Data Sampling** — Quick data preview
- **Statistics** — Compute dataset statistics (mean, std, percentiles, distribution)

## Tools

### datalake_list_schemas
List all available schemas in datalake.
- No inputs required
- Returns: list of schema names and metadata

### datalake_get_schema
Get schema details including tables and columns.
- Inputs: `schema_name` (string)
- Returns: schema structure with table definitions

### datalake_list_datasets
List all available datasets in datalake.
- No inputs required
- Returns: list of dataset names and metadata

### datalake_get_dataset
Get dataset details and metadata.
- Inputs: `dataset_id` (string)
- Returns: dataset information, size, row count, schema

### datalake_prepare_for_ml
Prepare dataset for ML training (train/test split, normalization, feature engineering).
- Inputs: `dataset_id` (string), `model_type` (string: classification|regression|clustering)
- Returns: prepared dataset info with training and testing sets

### datalake_sample_data
Get sample of data from dataset.
- Inputs: `dataset_id` (string), `limit` (integer, default: 10)
- Returns: sample rows and column metadata

### datalake_create_dataset
Create new dataset in datalake.
- Inputs: `name` (string), `schema` (object with column definitions), `description` (optional)
- Returns: created dataset ID and metadata

### datalake_compute_statistics
Compute statistics for dataset (mean, std, percentiles, distribution).
- Inputs: `dataset_id` (string)
- Returns: statistical summary for each column

## Installation

```bash
pip install -e .
```

## Configuration

Environment variables (prefix: `MCP_DATALAKE_`):

- `MCP_DATALAKE_BASE_URL` — platform-datalake API endpoint (default: `http://localhost:8005/api/v1`)
- `MCP_DATALAKE_API_KEY` — Authentication token
- `MCP_DATALAKE_TIMEOUT_SECONDS` — HTTP timeout (default: 30)
- `MCP_DATALAKE_VERIFY_SSL` — Verify SSL certificates (default: true)

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

Error types: `HTTPError`, `NotFound`, `BadRequest`, `Exception`

## Related

- platform-datalake API documentation
- DAI Workflow Engine (Fase 3+)
- ML data preparation workflows
