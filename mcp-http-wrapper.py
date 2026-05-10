#!/usr/bin/env python3
"""
MCP HTTP Wrapper - Connect Claude Code via stdio to remote HTTP MCPs
Usage: claude-code config: mcp-http-wrapper.py
"""

import sys
import json
import asyncio
import httpx
from typing import Optional, Dict, Any, List
import logging

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler('/tmp/mcp-wrapper.log')]
)
logger = logging.getLogger(__name__)

# Configuration
MCP_REGISTRY_URL = "http://claude-dev:8000"  # claude-dev VM with MCPs
TIMEOUT = 30.0

# MCP Port mapping (discovered dynamically, but fallback here)
MCP_PORTS = {
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
}

class MCPHTTPWrapper:
    def __init__(self, registry_url: str = MCP_REGISTRY_URL):
        self.registry_url = registry_url
        self.mcp_ports = MCP_PORTS.copy()
        self.tool_to_mcp = {}  # Maps tool_name -> mcp_name
        self.http_client = None

    async def initialize(self):
        """Initialize and discover MCPs from registry"""
        self.http_client = httpx.AsyncClient(timeout=TIMEOUT)
        try:
            # Discover all MCPs from registry
            response = await self.http_client.get(f"{self.registry_url}/services")
            services = response.json()

            logger.info(f"Discovered {len(services)} MCPs from registry")

            # Build tool to MCP mapping
            for service in services:
                mcp_name = service.get("name")
                port = service.get("port")
                if mcp_name and port:
                    self.mcp_ports[mcp_name] = port

                    # Get tools from this MCP
                    try:
                        tools_response = await self.http_client.get(
                            f"http://localhost:{port}/mcp/tools/list"
                        )
                        tools_data = tools_response.json()

                        if "result" in tools_data and "tools" in tools_data["result"]:
                            for tool in tools_data["result"]["tools"]:
                                tool_name = tool.get("name")
                                if tool_name:
                                    self.tool_to_mcp[tool_name] = mcp_name

                        logger.info(f"Loaded {len([t for t in self.tool_to_mcp if self.tool_to_mcp[t] == mcp_name])} tools from {mcp_name}:{port}")
                    except Exception as e:
                        logger.warning(f"Failed to load tools from {mcp_name}:{port}: {e}")

        except Exception as e:
            logger.warning(f"Failed to discover from registry: {e}. Using fallback ports.")

    async def get_mcp_url(self, mcp_name: str) -> str:
        """Get HTTP URL for an MCP"""
        port = self.mcp_ports.get(mcp_name)
        if not port:
            raise ValueError(f"Unknown MCP: {mcp_name}")
        return f"http://localhost:{port}"

    async def handle_initialize(self, msg_id: int) -> Dict[str, Any]:
        """Handle initialize request"""
        logger.info(f"Initializing wrapper (id={msg_id})")

        # Collect capabilities from all MCPs
        tools_list = []
        for tool_name in sorted(self.tool_to_mcp.keys()):
            mcp_name = self.tool_to_mcp[tool_name]
            tools_list.append({
                "name": tool_name,
                "description": f"Tool from {mcp_name}",
                "inputSchema": {"type": "object", "properties": {}, "required": []}
            })

        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {
                    "name": "mcp-http-wrapper",
                    "version": "1.0.0"
                }
            }
        }

    async def handle_tools_list(self, msg_id: int) -> Dict[str, Any]:
        """Handle tools/list request"""
        logger.info(f"Listing tools (id={msg_id})")

        tools = []
        for tool_name, mcp_name in self.tool_to_mcp.items():
            tools.append({
                "name": tool_name,
                "description": f"From {mcp_name}",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            })

        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {"tools": tools}
        }

    async def handle_tools_call(self, msg_id: int, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Handle tools/call request - route to appropriate MCP"""
        logger.info(f"Calling tool: {tool_name} with args: {arguments} (id={msg_id})")

        if tool_name not in self.tool_to_mcp:
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {
                    "code": -32601,
                    "message": f"Tool not found: {tool_name}"
                }
            }

        mcp_name = self.tool_to_mcp[tool_name]

        try:
            mcp_url = await self.get_mcp_url(mcp_name)

            # Forward request to remote MCP
            request_body = {
                "jsonrpc": "2.0",
                "id": msg_id,
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": arguments
                }
            }

            logger.info(f"Forwarding to {mcp_name} at {mcp_url}/mcp/tools/call")

            response = await self.http_client.post(
                f"{mcp_url}/mcp/tools/call",
                json=request_body,
                timeout=TIMEOUT
            )

            result = response.json()
            logger.info(f"Response from {mcp_name}: {result}")

            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": result.get("result", {"content": [{"type": "text", "text": "No result"}]})
            }

        except httpx.TimeoutException:
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {
                    "code": -32603,
                    "message": f"Timeout calling {mcp_name}"
                }
            }
        except Exception as e:
            logger.error(f"Error calling {mcp_name}: {e}")
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {
                    "code": -32603,
                    "message": f"Error calling {mcp_name}: {str(e)}"
                }
            }

    async def handle_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Handle incoming JSON-RPC request"""
        msg_id = request.get("id", 0)
        method = request.get("method", "")
        params = request.get("params", {})

        logger.info(f"Request: method={method}, id={msg_id}")

        if method == "initialize":
            return await self.handle_initialize(msg_id)

        elif method == "tools/list":
            return await self.handle_tools_list(msg_id)

        elif method == "tools/call":
            tool_name = params.get("name", "")
            arguments = params.get("arguments", {})
            return await self.handle_tools_call(msg_id, tool_name, arguments)

        else:
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {
                    "code": -32601,
                    "message": f"Method not found: {method}"
                }
            }

    async def run(self):
        """Main loop - read from stdin, write to stdout"""
        await self.initialize()

        loop = asyncio.get_event_loop()

        while True:
            try:
                # Read line from stdin
                line = await loop.run_in_executor(None, sys.stdin.readline)

                if not line:
                    logger.info("EOF on stdin, exiting")
                    break

                # Parse JSON-RPC request
                request = json.loads(line)
                logger.debug(f"Received: {request}")

                # Handle request
                response = await self.handle_request(request)

                # Send response on stdout
                sys.stdout.write(json.dumps(response) + "\n")
                sys.stdout.flush()
                logger.debug(f"Sent: {response}")

            except json.JSONDecodeError as e:
                logger.error(f"JSON decode error: {e}")
                error_response = {
                    "jsonrpc": "2.0",
                    "id": 0,
                    "error": {
                        "code": -32700,
                        "message": f"Parse error: {str(e)}"
                    }
                }
                sys.stdout.write(json.dumps(error_response) + "\n")
                sys.stdout.flush()
            except Exception as e:
                logger.error(f"Unexpected error: {e}")
                error_response = {
                    "jsonrpc": "2.0",
                    "id": 0,
                    "error": {
                        "code": -32603,
                        "message": f"Internal error: {str(e)}"
                    }
                }
                sys.stdout.write(json.dumps(error_response) + "\n")
                sys.stdout.flush()

    async def cleanup(self):
        """Cleanup resources"""
        if self.http_client:
            await self.http_client.aclose()

async def main():
    """Entry point"""
    wrapper = MCPHTTPWrapper()
    try:
        await wrapper.run()
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    finally:
        await wrapper.cleanup()

if __name__ == "__main__":
    asyncio.run(main())
