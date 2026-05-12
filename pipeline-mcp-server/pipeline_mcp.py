#!/usr/bin/env python3
"""
pipeline-mcp - FastAPI HTTP Service
Port: 7108
"""
import os
from fastapi import FastAPI
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="pipeline-mcp",
    version="1.0.0"
)

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

class PipelineMcpMCPService:
    def __init__(self):
        self.name = "pipeline-mcp"
        self.version = "1.0"        self.tools = [ { "name": "trigger_pipeline", "description": "trigger pipeline", "inputSchema": { "type": "object", "properties": {}, "required": [] } }, { "name": "check_status", "description": "check status", "inputSchema": { "type": "object", "properties": {}, "required": [] } }, { "name": "list_gates", "description": "list gates", "inputSchema": { "type": "object", "properties": {}, "required": [] } }, { "name": "promote_build", "description": "promote build", "inputSchema": { "type": "object", "properties": {}, "required": [] } }, { "name": "rollback", "description": "rollback", "inputSchema": { "type": "object", "properties": {}, "required": [] } }, { "name": "skip_gate", "description": "skip gate", "inputSchema": { "type": "object", "properties": {}, "required": [] } }, { "name": "view_logs", "description": "view logs", "inputSchema": { "type": "object", "properties": {}, "required": [] } }, { "name": "get_artifacts", "description": "get artifacts", "inputSchema": { "type": "object", "properties": {}, "required": [] } }, { "name": "retry_stage", "description": "retry stage", "inputSchema": { "type": "object", "properties": {}, "required": [] } }, { "name": "cancel_pipeline", "description": "cancel pipeline", "inputSchema": { "type": "object", "properties": {}, "required": [] } } ]

    def initialize(self, msg_id: int) -> Dict[str, Any]:
        return {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": self.name, "version": self.version}
        }

    def list_tools(self) -> List[Dict[str, Any]]:
        return self.tools

    def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        logger.info(f"Tool {tool_name} called with {arguments}")
        return f"Tool {tool_name} executed"

service = PipelineMcpMCPService()

@app.post("/mcp/initialize")
async def mcp_initialize(request: MCPRequest) -> MCPResponse:
    result = service.initialize(request.id)
    return MCPResponse(id=request.id, result=result)

@app.get("/mcp/tools/list")
@app.post("/mcp/tools/list")
async def mcp_tools_list(request: Optional[MCPRequest] = None) -> MCPResponse:
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
    return {"name": "pipeline-mcp", "version": "1.0", "tools": len(service.tools)}

@app.get("/")
async def root():
    return {"service": "pipeline-mcp", "version": "1.0"}

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 7108))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
