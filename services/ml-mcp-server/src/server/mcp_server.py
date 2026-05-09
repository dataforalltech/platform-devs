"""MCP Server for ML — model training, evaluation, and inference."""

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from src.tools.ml_tools import (
    ml_batch_predict,
    ml_delete_model,
    ml_evaluate_model,
    ml_export_model,
    ml_get_feature_importance,
    ml_get_model,
    ml_list_models,
    ml_predict,
    ml_train_model,
)

# Initialize MCP server
server = Server("ml-mcp")


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List available ML tools."""
    return [
        Tool(
            name="ml_train_model",
            description="Train a new machine learning model",
            inputSchema={
                "type": "object",
                "properties": {
                    "dataset_id": {"type": "string", "description": "ID of the prepared dataset"},
                    "model_type": {
                        "type": "string",
                        "description": "Type of model (classification, regression, clustering)",
                    },
                    "hyperparameters": {
                        "type": "object",
                        "description": "Optional model hyperparameters",
                    },
                },
                "required": ["dataset_id", "model_type"],
            },
        ),
        Tool(
            name="ml_evaluate_model",
            description="Evaluate trained model on test dataset",
            inputSchema={
                "type": "object",
                "properties": {
                    "model_id": {"type": "string", "description": "ID of the trained model"},
                    "test_dataset_id": {"type": "string", "description": "ID of the test dataset"},
                },
                "required": ["model_id", "test_dataset_id"],
            },
        ),
        Tool(
            name="ml_get_model",
            description="Get model details and metadata",
            inputSchema={
                "type": "object",
                "properties": {
                    "model_id": {"type": "string", "description": "ID of the model"},
                },
                "required": ["model_id"],
            },
        ),
        Tool(
            name="ml_list_models",
            description="List all trained models",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="ml_predict",
            description="Run inference on trained model",
            inputSchema={
                "type": "object",
                "properties": {
                    "model_id": {"type": "string", "description": "ID of the trained model"},
                    "data": {"type": "object", "description": "Input data for prediction"},
                },
                "required": ["model_id", "data"],
            },
        ),
        Tool(
            name="ml_delete_model",
            description="Delete a model",
            inputSchema={
                "type": "object",
                "properties": {
                    "model_id": {"type": "string", "description": "ID of the model to delete"},
                },
                "required": ["model_id"],
            },
        ),
        Tool(
            name="ml_get_feature_importance",
            description="Get feature importance for trained model (regression/classification)",
            inputSchema={
                "type": "object",
                "properties": {
                    "model_id": {"type": "string", "description": "ID of the trained model"},
                },
                "required": ["model_id"],
            },
        ),
        Tool(
            name="ml_export_model",
            description="Export trained model in specified format",
            inputSchema={
                "type": "object",
                "properties": {
                    "model_id": {"type": "string", "description": "ID of the model"},
                    "format": {
                        "type": "string",
                        "description": "Export format (onnx, pkl, tf, pytorch)",
                        "default": "onnx",
                    },
                },
                "required": ["model_id"],
            },
        ),
        Tool(
            name="ml_batch_predict",
            description="Run batch inference on entire dataset",
            inputSchema={
                "type": "object",
                "properties": {
                    "model_id": {"type": "string", "description": "ID of the trained model"},
                    "dataset_id": {"type": "string", "description": "ID of the dataset for predictions"},
                },
                "required": ["model_id", "dataset_id"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Execute a tool and return result as JSON."""
    try:
        if name == "ml_train_model":
            result = await ml_train_model(
                arguments["dataset_id"],
                arguments["model_type"],
                arguments.get("hyperparameters"),
            )
        elif name == "ml_evaluate_model":
            result = await ml_evaluate_model(arguments["model_id"], arguments["test_dataset_id"])
        elif name == "ml_get_model":
            result = await ml_get_model(arguments["model_id"])
        elif name == "ml_list_models":
            result = await ml_list_models()
        elif name == "ml_predict":
            result = await ml_predict(arguments["model_id"], arguments["data"])
        elif name == "ml_delete_model":
            result = await ml_delete_model(arguments["model_id"])
        elif name == "ml_get_feature_importance":
            result = await ml_get_feature_importance(arguments["model_id"])
        elif name == "ml_export_model":
            result = await ml_export_model(arguments["model_id"], arguments.get("format", "onnx"))
        elif name == "ml_batch_predict":
            result = await ml_batch_predict(arguments["model_id"], arguments["dataset_id"])
        else:
            result = '{"error": "UnknownTool", "details": "Tool not found"}'

        return [TextContent(type="text", text=result)]
    except Exception as e:
        error_json = f'{{"error": "Exception", "details": "{str(e)}"}}'
        return [TextContent(type="text", text=error_json)]


async def main():
    """Run the MCP server."""
    async with stdio_server(server) as streams:
        await streams.wait_closed()


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
