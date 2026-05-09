# ml-mcp — Model Training, Evaluation & Inference

MCP Server for platform-ml. Exposes ML model operations as standardized tools for training, evaluation, and inference.

## Features

- **Model Training** — Train classification, regression, and clustering models
- **Evaluation** — Measure model performance on test datasets
- **Inference** — Single and batch predictions
- **Model Management** — CRUD operations on models
- **Feature Analysis** — Extract feature importance
- **Model Export** — Export in multiple formats (ONNX, pkl, TF, PyTorch)

## Tools

### ml_train_model
Train a new machine learning model.
- Inputs: `dataset_id`, `model_type` (classification|regression|clustering), optional `hyperparameters`
- Returns: trained model ID, model metadata, training metrics

### ml_evaluate_model
Evaluate trained model on test dataset.
- Inputs: `model_id`, `test_dataset_id`
- Returns: evaluation metrics (accuracy, precision, recall, AUC, etc.)

### ml_get_model
Get model details and metadata.
- Inputs: `model_id`
- Returns: model information, hyperparameters, training history

### ml_list_models
List all trained models.
- No inputs required
- Returns: list of models with metadata

### ml_predict
Run inference on trained model (single prediction).
- Inputs: `model_id`, `data` (dict with input features)
- Returns: prediction result with confidence score

### ml_delete_model
Delete a model.
- Inputs: `model_id`
- Returns: deletion confirmation

### ml_get_feature_importance
Get feature importance for trained model (regression/classification).
- Inputs: `model_id`
- Returns: ranked list of features by importance

### ml_export_model
Export trained model in specified format.
- Inputs: `model_id`, optional `format` (onnx|pkl|tf|pytorch, default: onnx)
- Returns: export URL or download link

### ml_batch_predict
Run batch inference on entire dataset.
- Inputs: `model_id`, `dataset_id`
- Returns: job ID and status (async operation)

## Installation

```bash
pip install -e .
```

## Configuration

Environment variables (prefix: `MCP_ML_`):

- `MCP_ML_BASE_URL` — platform-ml API endpoint (default: `http://localhost:8006/api/v1`)
- `MCP_ML_API_KEY` — Authentication token
- `MCP_ML_TIMEOUT_SECONDS` — HTTP timeout (default: 60)
- `MCP_ML_VERIFY_SSL` — Verify SSL certificates (default: true)

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

- platform-ml API documentation
- DAI Workflow Engine (Fase 3+)
- ML model training workflows (gerar_modelo_ml)
