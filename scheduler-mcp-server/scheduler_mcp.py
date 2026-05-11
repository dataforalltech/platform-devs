#!/usr/bin/env python3
"""
scheduler-mcp - FastAPI HTTP Service
Port: 7114
"""
import os
from fastapi import FastAPI
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="scheduler-mcp",
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

class SchedulerMcpMCPService:
    def __init__(self):
        self.name = "scheduler-mcp"
        self.version = "1.0"
        # TODO: Import tools from original scheduler-mcp.py
        self.tools = [ { "name": "create_task", "description": "create task", "inputSchema": { "type": "object", "properties": {}, "required": [] } }, { "name": "schedule_job", "description": "schedule job", "inputSchema": { "type": "object", "properties": {}, "required": [] } }, { "name": "list_scheduled", "description": "list scheduled", "inputSchema": { "type": "object", "properties": {}, "required": [] } }, { "name": "cancel_task", "description": "cancel task", "inputSchema": { "type": "object", "properties": {}, "required": [] } }, { "name": "check_history", "description": "check history", "inputSchema": { "type": "object", "properties": {}, "required": [] } }, { "name": "update_schedule", "description": "update schedule", "inputSchema": { "type": "object", "properties": {}, "required": [] } }, { "name": "get_task_status", "description": "get task status", "inputSchema": { "type": "object", "properties": {}, "required": [] } }, { "name": "retry_task", "description": "retry task", "inputSchema": { "type": "object", "properties": {}, "required": [] } }, { "name": "pause_task", "description": "pause task", "inputSchema": { "type": "object", "properties": {}, "required": [] } }, { "name": "resume_task", "description": "resume task", "inputSchema": { "type": "object", "properties": {}, "required": [] } } ]

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

service = SchedulerMcpMCPService()

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
    return {"name": "scheduler-mcp", "version": "1.0", "tools": len(service.tools)}

@app.get("/")
async def root():
    return {"service": "scheduler-mcp", "version": "1.0"}

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 7114))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
