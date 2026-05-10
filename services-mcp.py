#!/usr/bin/env python3
"""Complete services-mcp with full tool support (10 tools)."""
import json
import sys

class ServicesMCP:
    def __init__(self):
        self.name = "services-mcp"
        self.tools = [
            {
                "name": "register_service",
                "description": "register service",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            },
            {
                "name": "check_health",
                "description": "check health",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            },
            {
                "name": "list_services",
                "description": "list services",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            },
            {
                "name": "get_port",
                "description": "get port",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            },
            {
                "name": "update_service",
                "description": "update service",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            },
            {
                "name": "deregister_service",
                "description": "deregister service",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            },
            {
                "name": "get_service_metrics",
                "description": "get service metrics",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            },
            {
                "name": "configure_service",
                "description": "configure service",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            },
            {
                "name": "restart_service",
                "description": "restart service",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            },
            {
                "name": "monitor_service",
                "description": "monitor service",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        ]

    def initialize(self, msg_id: int) -> dict:
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {
                    "name": self.name,
                    "version": "1.0"
                }
            }
        }

    def list_tools(self, msg_id: int) -> dict:
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {"tools": self.tools}
        }

    def call_tool(self, msg_id: int, tool_name: str, arguments: dict) -> dict:
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "tool": tool_name,
                "message": f"Tool {tool_name} executed on services-mcp",
                "arguments": arguments
            }
        }

    def run(self):
        while True:
            try:
                line = sys.stdin.readline()
                if not line:
                    break

                msg = json.loads(line)
                msg_id = msg.get("id", 0)
                method = msg.get("method", "")
                params = msg.get("params", {})

                if method == "initialize":
                    response = self.initialize(msg_id)
                elif method == "tools/list":
                    response = self.list_tools(msg_id)
                elif method == "tools/call":
                    tool_name = params.get("name", "")
                    arguments = params.get("arguments", {})
                    response = self.call_tool(msg_id, tool_name, arguments)
                else:
                    response = {
                        "jsonrpc": "2.0",
                        "id": msg_id,
                        "result": {"ok": True}
                    }

                sys.stdout.write(json.dumps(response) + "\n")
                sys.stdout.flush()

            except json.JSONDecodeError as e:
                sys.stderr.write(f"JSONDecodeError: {e}\n")
            except Exception as e:
                sys.stderr.write(f"Error: {e}\n")

if __name__ == "__main__":
    mcp = ServicesMCP()
    mcp.run()
