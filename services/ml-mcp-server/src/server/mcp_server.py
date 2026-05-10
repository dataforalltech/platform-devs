"""MCP Server for ML — 9 core tools for model management and training."""

import json
import logging
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from src.config.settings import settings
from src.tools.ml_tools import (
    create_model,
    deploy_model,
    evaluate_model,
    get_model,
    get_training_status,
    list_experiments,
    list_models,
    predict,
    train_model,
)

logger = logging.getLogger(__name__)

# Initialize MCP server
server = Server("ml-mcp")


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List available ML tools."""
    return [
        Tool(
            name="list_models",
            description="List all models for a tenant",
            inputSchema={
                "type": "object",
                "properties": {
                    "tenant_id": {"type": "string", "description": "Tenant identifier"},
                },
                "required": ["tenant_id"],
            },
        ),
        Tool(
            name="get_model",
            description="Get model details and metadata",
            inputSchema={
                "type": "object",
                "properties": {
                    "model_id": {"type": "string", "description": "Model identifier"},
                },
                "required": ["model_id"],
            },
        ),
        Tool(
            name="create_model",
            description="Create a new model definition",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Model name"},
                    "type": {
                        "type": "string",
                        "description": "Model type (classification, regression, clustering)",
                    },
                    "config": {
                        "type": "object",
                        "description": "Model configuration",
                    },
                },
                "required": ["name", "type", "config"],
            },
        ),
        Tool(
            name="train_model",
            description="Train a model",
            inputSchema={
                "type": "object",
                "properties": {
                    "model_id": {"type": "string", "description": "Model identifier"},
                    "dataset_id": {"type": "string", "description": "Dataset identifier"},
                    "hyperparams": {
                        "type": "object",
                        "description": "Optional hyperparameters",
                    },
                },
                "required": ["model_id", "dataset_id"],
            },
        ),
        Tool(
            name="get_training_status",
            description="Get status of a training job",
            inputSchema={
                "type": "object",
                "properties": {
                    "job_id": {"type": "string", "description": "Job identifier"},
                },
                "required": ["job_id"],
            },
        ),
        Tool(
            name="evaluate_model",
            description="Evaluate model on test dataset",
            inputSchema={
                "type": "object",
                "properties": {
                    "model_id": {"type": "string", "description": "Model identifier"},
                    "test_dataset_id": {
                        "type": "string",
                        "description": "Test dataset identifier",
                    },
                },
                "required": ["model_id", "test_dataset_id"],
            },
        ),
        Tool(
            name="deploy_model",
            description="Deploy model to environment",
            inputSchema={
                "type": "object",
                "properties": {
                    "model_id": {"type": "string", "description": "Model identifier"},
                    "version": {"type": "string", "description": "Model version"},
                    "environment": {
                        "type": "string",
                        "description": "Target environment (dev, staging, prod)",
                    },
                },
                "required": ["model_id", "version", "environment"],
            },
        ),
        Tool(
            name="predict",
            description="Run inference on model",
            inputSchema={
                "type": "object",
                "properties": {
                    "model_id": {"type": "string", "description": "Model identifier"},
                    "input_data": {
                        "type": "object",
                        "description": "Input features",
                    },
                },
                "required": ["model_id", "input_data"],
            },
        ),
        Tool(
            name="list_experiments",
            description="List experiments for a model",
            inputSchema={
                "type": "object",
                "properties": {
                    "model_id": {"type": "string", "description": "Model identifier"},
                },
                "required": ["model_id"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Execute a tool and return result as JSON."""
    logger.debug(f"Calling tool: {name} with args: {arguments}")
    try:
        if name == "list_models":
            result = await list_models(arguments["tenant_id"])
        elif name == "get_model":
            result = await get_model(arguments["model_id"])
        elif name == "create_model":
            result = await create_model(
                arguments["name"], arguments["type"], arguments["config"]
            )
        elif name == "train_model":
            result = await train_model(
                arguments["model_id"],
                arguments["dataset_id"],
                arguments.get("hyperparams"),
            )
        elif name == "get_training_status":
            result = await get_training_status(arguments["job_id"])
        elif name == "evaluate_model":
            result = await evaluate_model(
                arguments["model_id"], arguments["test_dataset_id"]
            )
        elif name == "deploy_model":
            result = await deploy_model(
                arguments["model_id"], arguments["version"], arguments["environment"]
            )
        elif name == "predict":
            result = await predict(arguments["model_id"], arguments["input_data"])
        elif name == "list_experiments":
            result = await list_experiments(arguments["model_id"])
        else:
            result = json.dumps(
                {"error": "ToolNotFound", "details": f"Tool '{name}' not found"}
            )

        return [TextContent(type="text", text=result)]
    except Exception as e:
        logger.exception(f"Error calling tool {name}")
        error_json = json.dumps({"error": "Exception", "details": str(e)})
        return [TextContent(type="text", text=error_json)]


async def main():
    """Run the MCP server."""
    logging.basicConfig(
        level=settings.MCP_ML_LOG_LEVEL if hasattr(settings, 'MCP_ML_LOG_LEVEL') else 'INFO',
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    logger.info("Starting ml-mcp server")
    async with stdio_server(server) as streams:
        await streams.wait_closed()


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
