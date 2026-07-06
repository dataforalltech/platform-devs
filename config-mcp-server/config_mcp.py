#!/usr/bin/env python3
"""
config-mcp - FastAPI HTTP Service
Port: 7100
"""

import logging
import os
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="config-mcp", version="1.0.0")


class MCPRequest(BaseModel):
    jsonrpc: str = "2.0"
    id: int
    method: str
    params: dict[str, Any] = Field(default_factory=dict)


class MCPResponse(BaseModel):
    jsonrpc: str = "2.0"
    id: int
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None


class ConfigMcpMCPService:
    def __init__(self):
        self.name = "config-mcp"
        self.version = "1.0"
        self.tools = [
            {
                "name": name,
                "description": description,
                "inputSchema": {"type": "object", "properties": {}, "required": []},
            }
            for name, description in (
                ("get_config", "get config"),
                ("set_config", "set config"),
                ("list_secrets", "list secrets"),
                ("validate_config", "validate config"),
                ("rotate_secrets", "rotate secrets"),
                ("get_secret", "get secret"),
                ("set_secret", "set secret"),
                ("delete_secret", "delete secret"),
                ("export_config", "export config"),
                ("import_config", "import config"),
            )
        ]

    def initialize(self, msg_id: int) -> dict[str, Any]:
        return {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": self.name, "version": self.version},
        }

    def list_tools(self) -> list[dict[str, Any]]:
        return self.tools

    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> str:
        logger.info(f"Tool {tool_name} called with {arguments}")
        return f"Tool {tool_name} executed"


service = ConfigMcpMCPService()


@app.post("/mcp/initialize")
async def mcp_initialize(request: MCPRequest) -> MCPResponse:
    result = service.initialize(request.id)
    return MCPResponse(id=request.id, result=result)


@app.get("/mcp/tools/list")
@app.post("/mcp/tools/list")
async def mcp_tools_list(request: MCPRequest | None = None) -> MCPResponse:
    msg_id = request.id if request else 1
    return MCPResponse(id=msg_id, result={"tools": service.list_tools()})


@app.post("/mcp/tools/call")
async def mcp_tools_call(request: MCPRequest) -> MCPResponse:
    tool_name = request.params.get("name")
    arguments = request.params.get("arguments", {})

    if not tool_name:
        return MCPResponse(id=request.id, error={"code": -32602, "message": "Missing name"})

    try:
        result = service.call_tool(tool_name, arguments)
        return MCPResponse(id=request.id, result={"content": [{"type": "text", "text": result}]})
    except Exception as e:
        return MCPResponse(id=request.id, error={"code": -32603, "message": str(e)})


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.get("/info")
async def info():
    return {"name": "config-mcp", "version": "1.0", "tools": len(service.tools)}


@app.get("/")
async def root():
    return {"service": "config-mcp", "version": "1.0"}


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 7100))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
