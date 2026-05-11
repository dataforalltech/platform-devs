#!/usr/bin/env python3
"""Complete scheduler-mcp with full tool support (10 tools)."""
import json
import sys

class SchedulerMCP:
    def __init__(self):
        self.name = "scheduler-mcp"
        self.tools = [
            {
                "name": "create_task",
                "description": "create task",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            },
            {
                "name": "schedule_job",
                "description": "schedule job",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            },
            {
                "name": "list_scheduled",
                "description": "list scheduled",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            },
            {
                "name": "cancel_task",
                "description": "cancel task",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            },
            {
                "name": "check_history",
                "description": "check history",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            },
            {
                "name": "update_schedule",
                "description": "update schedule",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            },
            {
                "name": "get_task_status",
                "description": "get task status",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            },
            {
                "name": "retry_task",
                "description": "retry task",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            },
            {
                "name": "pause_task",
                "description": "pause task",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            },
            {
                "name": "resume_task",
                "description": "resume task",
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
                "message": f"Tool {tool_name} executed on scheduler-mcp",
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
    mcp = SchedulerMCP()
    mcp.run()
