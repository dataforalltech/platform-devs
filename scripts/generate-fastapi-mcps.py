#!/usr/bin/env python3
"""
Generate FastAPI MCPs from template
Simplest approach: create template for each MCP without parsing
"""

import os
from pathlib import Path

# MCP Configuration: name -> port
MCP_CONFIG = {
    "config-mcp": 7100,
    "agent-twin-mcp": 7101,
    "session-mcp": 7102,
    "auth-mcp": 7103,
    "admin-mcp": 7104,
    "audit-mcp": 7105,
    "infra-mcp": 7106,
    "services-mcp": 7107,
    "pipeline-mcp": 7108,
    "qa-mcp": 7109,
    "deploy-mcp": 7110,
    "docs-mcp": 7111,
    "ai-governance-mcp": 7112,
    "governance-mcp": 7113,
    "scheduler-mcp": 7114,
    "connectors-mcp": 7115,
    "cache-mcp": 7116,
    "test-mcp": 7117,
}

FASTAPI_TEMPLATE = '''#!/usr/bin/env python3
"""
{mcp_name} - FastAPI HTTP Service
Port: {port}
"""
import os
from fastapi import FastAPI
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="{mcp_name}",
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

class {class_name}Service:
    def __init__(self):
        self.name = "{mcp_name}"
        self.version = "1.0"
        # TODO: Import tools from original {mcp_name}.py
        self.tools = []

    def initialize(self, msg_id: int) -> Dict[str, Any]:
        return {{
            "protocolVersion": "2024-11-05",
            "capabilities": {{"tools": {{}}}},
            "serverInfo": {{"name": self.name, "version": self.version}}
        }}

    def list_tools(self) -> List[Dict[str, Any]]:
        return self.tools

    def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        logger.info(f"Tool {{tool_name}} called with {{arguments}}")
        return f"Tool {{tool_name}} executed"

service = {class_name}Service()

@app.post("/mcp/initialize")
async def mcp_initialize(request: MCPRequest) -> MCPResponse:
    result = service.initialize(request.id)
    return MCPResponse(id=request.id, result=result)

@app.get("/mcp/tools/list")
@app.post("/mcp/tools/list")
async def mcp_tools_list(request: Optional[MCPRequest] = None) -> MCPResponse:
    msg_id = request.id if request else 1
    return MCPResponse(id=msg_id, result={{"tools": service.list_tools()}})

@app.post("/mcp/tools/call")
async def mcp_tools_call(request: MCPRequest) -> MCPResponse:
    tool_name = request.params.get("name")
    arguments = request.params.get("arguments", {{}})

    if not tool_name:
        return MCPResponse(id=request.id, error={{"code": -32602, "message": "Missing name"}})

    try:
        result = service.call_tool(tool_name, arguments)
        return MCPResponse(id=request.id, result={{"content": [{{"type": "text", "text": result}}]}})
    except Exception as e:
        return MCPResponse(id=request.id, error={{"code": -32603, "message": str(e)}})

@app.get("/health")
async def health():
    return {{"status": "healthy"}}

@app.get("/info")
async def info():
    return {{"name": "{mcp_name}", "version": "1.0", "tools": len(service.tools)}}

@app.get("/")
async def root():
    return {{"service": "{mcp_name}", "version": "1.0"}}

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", {port}))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
'''

DOCKERFILE_TEMPLATE = '''FROM python:3.11-slim
WORKDIR /app
RUN pip install --no-cache-dir fastapi==0.104.1 uvicorn[standard]==0.24.0 pydantic==2.4.2
COPY {mcp_file} .
EXPOSE {port}
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \\
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:{port}/health')" || exit 1
CMD ["python3", "-m", "uvicorn", "{module_name}:app", "--host", "0.0.0.0", "--port", "{port}"]
'''

def generate_mcp(mcp_name: str, port: int):
    """Generate FastAPI MCP for given name and port"""
    # Create directory
    mcp_dir = Path(f"/home/dev/repos/platform-devs/{mcp_name}-server")
    mcp_dir.mkdir(exist_ok=True)

    # Generate class name
    class_name = "".join(word.capitalize() for word in mcp_name.split("-")) + "MCP"
    mcp_file = f"{mcp_name.replace('-', '_')}"

    # Generate FastAPI code
    fastapi_code = FASTAPI_TEMPLATE.format(
        mcp_name=mcp_name,
        port=port,
        class_name=class_name,
    )

    # Write FastAPI file
    fastapi_path = mcp_dir / f"{mcp_file}.py"
    with open(fastapi_path, "w") as f:
        f.write(fastapi_code)
    print(f"✓ {mcp_name}: {fastapi_path}")

    # Generate Dockerfile
    dockerfile_code = DOCKERFILE_TEMPLATE.format(
        mcp_file=f"{mcp_file}.py",
        module_name=mcp_file,
        port=port
    )

    dockerfile_path = mcp_dir / "Dockerfile"
    with open(dockerfile_path, "w") as f:
        f.write(dockerfile_code)

if __name__ == "__main__":
    print("Generating FastAPI MCPs...")
    for mcp_name, port in sorted(MCP_CONFIG.items()):
        try:
            generate_mcp(mcp_name, port)
        except Exception as e:
            print(f"✗ {mcp_name}: {e}")

    print("\n✓ All FastAPI MCPs generated!")
    print("\nNext:")
    print("  1. Copy tools from original *-mcp.py to new *-mcp-server/*_mcp.py")
    print("  2. Test: python config-mcp-server/config_mcp.py")
    print("  3. Build: docker-compose build")
    print("  4. Run: docker-compose up -d")
