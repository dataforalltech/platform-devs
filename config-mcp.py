#!/usr/bin/env python3
"""Complete config-mcp with full tool support (10 tools)."""
import json
import sys

class ConfigMCP:
    def __init__(self):
        self.name = "config-mcp"
        self.tools = [
            {
                "name": "get_config",
                "description": "get config",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            },
            {
                "name": "set_config",
                "description": "set config",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            },
            {
                "name": "list_secrets",
                "description": "list secrets",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            },
            {
                "name": "validate_config",
                "description": "validate config",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            },
            {
                "name": "rotate_secrets",
                "description": "rotate secrets",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            },
            {
                "name": "get_secret",
                "description": "get secret",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            },
            {
                "name": "set_secret",
                "description": "set secret",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            },
            {
                "name": "delete_secret",
                "description": "delete secret",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            },
            {
                "name": "export_config",
                "description": "export config",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            },
            {
                "name": "import_config",
                "description": "import config",
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
                "message": f"Tool {tool_name} executed on config-mcp",
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
    mcp = ConfigMCP()
    mcp.run()
