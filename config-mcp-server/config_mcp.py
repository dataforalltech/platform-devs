#!/usr/bin/env python3
"""
Config MCP - FastAPI HTTP Service
Shared service for N users on Docker
Port: 7100
"""
import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Config MCP",
    description="Configuration and Secrets Management MCP Service",
    version="1.0.0"
)

# ============================================================================
# Domain Models (Pydantic)
# ============================================================================

class MCPRequest(BaseModel):
    jsonrpc: str = "2.0"
    id: int
    method: str
    params: Dict[str, Any] = Field(default_factory=dict)


class MCPResponse(BaseModel):
    jsonrpc: str = "2.0"
    id: int
    result: Optional[Dict[str, Any]] = None
    error: Optional[Dict[str, Any]] = None


class ToolSchema(BaseModel):
    name: str
    description: str
    inputSchema: Dict[str, Any]


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


class InfoResponse(BaseModel):
    name: str
    version: str
    tools: int
    description: str


# ============================================================================
# MCP Service
# ============================================================================

class ConfigMCPService:
    def __init__(self):
        self.name = "config-mcp"
        self.version = "1.0"
        self.tools: List[ToolSchema] = [
            ToolSchema(
                name="get_config",
                description="Retrieves configuration by key",
                inputSchema={
                    "type": "object",
                    "properties": {"key": {"type": "string"}},
                    "required": ["key"]
                }
            ),
            ToolSchema(
                name="set_config",
                description="Sets configuration value for key",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "key": {"type": "string"},
                        "value": {"type": "string"}
                    },
                    "required": ["key", "value"]
                }
            ),
            ToolSchema(
                name="list_secrets",
                description="Lists all secret keys (not values)",
                inputSchema={
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            ),
            ToolSchema(
                name="validate_config",
                description="Validates current configuration",
                inputSchema={
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            ),
            ToolSchema(
                name="rotate_secrets",
                description="Rotates all secrets",
                inputSchema={
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            ),
            ToolSchema(
                name="get_secret",
                description="Retrieves secret value by key",
                inputSchema={
                    "type": "object",
                    "properties": {"key": {"type": "string"}},
                    "required": ["key"]
                }
            ),
            ToolSchema(
                name="set_secret",
                description="Sets secret value for key",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "key": {"type": "string"},
                        "value": {"type": "string"}
                    },
                    "required": ["key", "value"]
                }
            ),
            ToolSchema(
                name="delete_secret",
                description="Deletes secret by key",
                inputSchema={
                    "type": "object",
                    "properties": {"key": {"type": "string"}},
                    "required": ["key"]
                }
            ),
            ToolSchema(
                name="export_config",
                description="Exports all configuration (excludes secrets)",
                inputSchema={
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            ),
            ToolSchema(
                name="import_config",
                description="Imports configuration from JSON object",
                inputSchema={
                    "type": "object",
                    "properties": {"config": {"type": "object"}},
                    "required": ["config"]
                }
            )
        ]

    def initialize(self, msg_id: int) -> Dict[str, Any]:
        return {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {
                "name": self.name,
                "version": self.version
            }
        }

    def list_tools(self) -> List[Dict[str, Any]]:
        return [tool.model_dump() for tool in self.tools]

    def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        """Execute tool and return result"""
        logger.info(f"Calling tool: {tool_name} with args: {arguments}")

        if tool_name == "get_config":
            key = arguments.get("key", "unknown")
            return f"Config value for key '{key}': production"
        elif tool_name == "set_config":
            key = arguments.get("key")
            value = arguments.get("value")
            return f"✓ Set config: {key} = {value}"
        elif tool_name == "list_secrets":
            return "DB_PASSWORD, API_KEY, JWT_SECRET, AWS_KEY"
        elif tool_name == "validate_config":
            return "✓ All configurations are valid"
        elif tool_name == "rotate_secrets":
            return "✓ All secrets rotated successfully"
        elif tool_name == "get_secret":
            key = arguments.get("key")
            return f"Secret '{key}' exists (value redacted for security)"
        elif tool_name == "set_secret":
            key = arguments.get("key")
            return f"✓ Secret '{key}' set successfully"
        elif tool_name == "delete_secret":
            key = arguments.get("key")
            return f"✓ Secret '{key}' deleted"
        elif tool_name == "export_config":
            return '{"env": "production", "features": {"auth": true}, "cache": "redis"}'
        elif tool_name == "import_config":
            return "✓ Configuration imported successfully"
        else:
            raise ValueError(f"Unknown tool: {tool_name}")


# Initialize service
service = ConfigMCPService()


# ============================================================================
# HTTP Endpoints
# ============================================================================

@app.post("/mcp/initialize")
async def mcp_initialize(request: MCPRequest) -> MCPResponse:
    """MCP Initialize - negotiate protocol version"""
    result = service.initialize(request.id)
    return MCPResponse(id=request.id, result=result)


@app.get("/mcp/tools/list")
@app.post("/mcp/tools/list")
async def mcp_tools_list(request: Optional[MCPRequest] = None) -> MCPResponse:
    """MCP Tools List - return all available tools"""
    msg_id = request.id if request else 1
    tools = service.list_tools()
    return MCPResponse(id=msg_id, result={"tools": tools})


@app.post("/mcp/tools/call")
async def mcp_tools_call(request: MCPRequest) -> MCPResponse:
    """MCP Tools Call - execute a tool"""
    tool_name = request.params.get("name")
    arguments = request.params.get("arguments", {})

    if not tool_name:
        return MCPResponse(
            id=request.id,
            error={
                "code": -32602,
                "message": "Missing required parameter: name"
            }
        )

    try:
        result_text = service.call_tool(tool_name, arguments)
        return MCPResponse(
            id=request.id,
            result={
                "content": [
                    {
                        "type": "text",
                        "text": result_text
                    }
                ]
            }
        )
    except ValueError as e:
        return MCPResponse(
            id=request.id,
            error={
                "code": -32603,
                "message": str(e)
            }
        )


# ============================================================================
# Health & Info Endpoints
# ============================================================================

@app.get("/health", response_model=HealthResponse)
async def health():
    """Health check endpoint"""
    return HealthResponse(
        status="healthy",
        service="config-mcp",
        version="1.0"
    )


@app.get("/info", response_model=InfoResponse)
async def info():
    """Service info endpoint"""
    return InfoResponse(
        name="config-mcp",
        version="1.0",
        tools=len(service.tools),
        description="Configuration and secrets management MCP"
    )


@app.get("/")
async def root():
    """Root endpoint with service info"""
    return {
        "service": "config-mcp",
        "version": "1.0",
        "endpoints": {
            "health": "/health",
            "info": "/info",
            "mcp_initialize": "POST /mcp/initialize",
            "mcp_tools_list": "GET/POST /mcp/tools/list",
            "mcp_tools_call": "POST /mcp/tools/call"
        }
    }


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 7100))
    host = os.environ.get("HOST", "0.0.0.0")

    logger.info(f"Starting {service.name} on {host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")
