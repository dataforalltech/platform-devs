#!/usr/bin/env python3
"""
Convert existing MCP from stdin/stdout to FastAPI + Docker

Usage: python convert-mcp-to-fastapi.py config-mcp 7100

This script:
1. Reads the original MCP tools definition
2. Generates FastAPI implementation
3. Creates Dockerfile
4. Updates docker-compose.yml
"""

import sys
import json
import os
from pathlib import Path
from typing import List, Dict, Any

TEMPLATE_FASTAPI = '''#!/usr/bin/env python3
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
    description="{description}",
    version="1.0.0"
)

# ============================================================================
# Domain Models
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

# ============================================================================
# MCP Service: {mcp_name}
# ============================================================================

class {class_name}Service:
    def __init__(self):
        self.name = "{mcp_name}"
        self.version = "1.0"
        self.tools = {tools_json}

    def initialize(self, msg_id: int) -> Dict[str, Any]:
        return {{
            "protocolVersion": "2024-11-05",
            "capabilities": {{"tools": {{}}}},
            "serverInfo": {{
                "name": self.name,
                "version": self.version
            }}
        }}

    def list_tools(self) -> List[Dict[str, Any]]:
        return self.tools

    def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        """Execute tool and return result"""
        logger.info(f"Calling tool: {{tool_name}} with args: {{arguments}}")

        # TODO: Implement tool dispatch logic
        return f"Tool {{tool_name}} executed successfully"

# Initialize service
service = {class_name}Service()

# ============================================================================
# HTTP Routes (MCP Protocol over HTTP)
# ============================================================================

@app.post("/mcp/initialize")
async def mcp_initialize(request: MCPRequest) -> MCPResponse:
    result = service.initialize(request.id)
    return MCPResponse(id=request.id, result=result)

@app.get("/mcp/tools/list")
@app.post("/mcp/tools/list")
async def mcp_tools_list(request: Optional[MCPRequest] = None) -> MCPResponse:
    msg_id = request.id if request else 1
    tools = service.list_tools()
    return MCPResponse(id=msg_id, result={{"tools": tools}})

@app.post("/mcp/tools/call")
async def mcp_tools_call(request: MCPRequest) -> MCPResponse:
    tool_name = request.params.get("name")
    arguments = request.params.get("arguments", {{}})

    if not tool_name:
        return MCPResponse(
            id=request.id,
            error={{"code": -32602, "message": "Missing required parameter: name"}}
        )

    try:
        result_text = service.call_tool(tool_name, arguments)
        return MCPResponse(
            id=request.id,
            result={{"content": [{{"type": "text", "text": result_text}}]}}
        )
    except ValueError as e:
        return MCPResponse(
            id=request.id,
            error={{"code": -32603, "message": str(e)}}
        )

@app.get("/health")
async def health():
    return {{"status": "healthy", "service": "{mcp_name}"}}

@app.get("/info")
async def info():
    return {{
        "name": "{mcp_name}",
        "version": "1.0",
        "tools": len(service.tools),
        "description": "{description}"
    }}

@app.get("/")
async def root():
    return {{
        "service": "{mcp_name}",
        "version": "1.0",
        "endpoints": {{
            "health": "/health",
            "info": "/info",
            "mcp_initialize": "POST /mcp/initialize",
            "mcp_tools_list": "GET/POST /mcp/tools/list",
            "mcp_tools_call": "POST /mcp/tools/call"
        }}
    }}

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", {port}))
    host = os.environ.get("HOST", "0.0.0.0")
    logger.info(f"Starting {{service.name}} on {{host}}:{{port}}")
    uvicorn.run(app, host=host, port=port, log_level="info")
'''

TEMPLATE_DOCKERFILE = '''FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir \\
    fastapi==0.104.1 \\
    uvicorn[standard]==0.24.0 \\
    pydantic==2.4.2

COPY {mcp_file} .

EXPOSE {port}

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \\
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:{port}/health')" || exit 1

CMD ["python3", "-m", "uvicorn", "{mcp_module}:app", "--host", "0.0.0.0", "--port", "{port}"]
'''


def extract_tools(mcp_name: str) -> List[Dict[str, Any]]:
    """Extract tools from existing MCP Python file"""
    mcp_file = Path(f"/home/dev/repos/platform-devs/{mcp_name}.py")

    if not mcp_file.exists():
        print(f"ERROR: {mcp_file} not found")
        sys.exit(1)

    # Parse Python file to extract tools
    with open(mcp_file) as f:
        content = f.read()

    # Simple regex to find self.tools assignment
    import re
    match = re.search(r'self\.tools\s*=\s*(\[.*?\])', content, re.DOTALL)

    if not match:
        print(f"ERROR: Could not find self.tools in {mcp_file}")
        sys.exit(1)

    # Use eval to parse the Python list (dangerous but OK for this use case)
    try:
        tools = eval(match.group(1))
        return tools
    except Exception as e:
        print(f"ERROR: Could not parse tools: {e}")
        sys.exit(1)


def convert_mcp(mcp_name: str, port: int):
    """Convert MCP from stdin/stdout to FastAPI"""
    print(f"Converting {mcp_name} to FastAPI on port {port}...")

    # Create directory if needed
    mcp_dir = Path(f"/home/dev/repos/platform-devs/{mcp_name}-server")
    mcp_dir.mkdir(exist_ok=True)

    # Extract tools from existing MCP
    tools = extract_tools(mcp_name)
    print(f"  Found {len(tools)} tools")

    # Generate class name from mcp_name
    class_name = "".join(word.capitalize() for word in mcp_name.split("-")) + "MCP"
    mcp_file = f"{mcp_name.replace('-', '_')}"
    description = f"{mcp_name.title()} - MCP Service"

    # Generate FastAPI code
    fastapi_code = TEMPLATE_FASTAPI.format(
        mcp_name=mcp_name,
        mcp_file=f"{mcp_file}.py",
        class_name=class_name,
        port=port,
        description=description,
        tools_json=json.dumps(tools, indent=12)
    )

    # Write FastAPI file
    fastapi_file = mcp_dir / f"{mcp_file}.py"
    with open(fastapi_file, "w") as f:
        f.write(fastapi_code)
    print(f"  ✓ Created {fastapi_file}")

    # Generate Dockerfile
    dockerfile_code = TEMPLATE_DOCKERFILE.format(
        mcp_file=f"{mcp_file}.py",
        mcp_module=mcp_file,
        port=port
    )

    dockerfile = mcp_dir / "Dockerfile"
    with open(dockerfile, "w") as f:
        f.write(dockerfile_code)
    print(f"  ✓ Created {dockerfile}")

    # Generate docker-compose override
    compose_override = {
        "version": "3.9",
        "services": {
            mcp_name: {
                "build": {
                    "context": f"./{mcp_name}-server",
                    "dockerfile": "Dockerfile"
                },
                "ports": [f"{port}:{port}"],
                "environment": {
                    "PORT": port
                },
                "networks": ["mcp-network"]
            }
        },
        "networks": {
            "mcp-network": {
                "driver": "bridge"
            }
        }
    }

    override_file = mcp_dir / "docker-compose.override.yml"
    with open(override_file, "w") as f:
        json.dump(compose_override, f, indent=2)
    print(f"  ✓ Created {override_file}")

    print(f"✓ Conversion complete!")
    print(f"\nNext steps:")
    print(f"  1. Review {fastapi_file}")
    print(f"  2. Implement tool dispatch logic in call_tool()")
    print(f"  3. Test locally: python {fastapi_file}")
    print(f"  4. Test in Docker: docker build -t {mcp_name} {mcp_dir} && docker run -p {port}:{port} {mcp_name}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python convert-mcp-to-fastapi.py <mcp-name> <port>")
        print("\nExample:")
        print("  python convert-mcp-to-fastapi.py config-mcp 7100")
        print("  python convert-mcp-to-fastapi.py auth-mcp 7103")
        sys.exit(1)

    mcp_name = sys.argv[1]
    try:
        port = int(sys.argv[2])
    except ValueError:
        print(f"ERROR: Port must be an integer, got {sys.argv[2]}")
        sys.exit(1)

    convert_mcp(mcp_name, port)
