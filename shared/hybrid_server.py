"""Hybrid MCP Server — stdio (MCP puro) + HTTP (REST) simultaneamente."""
from __future__ import annotations

import asyncio
import json
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
import uvicorn
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool


class HybridMCPServer:
    """
    Runs MCP protocol on stdio (for Claude, mcp-registry) + HTTP REST API (for gateway, cross-MCP).
    Usage:
        server = HybridMCPServer("qazilla-mcp-server", _TOOLS, _DISPATCH)
        await server.run()
    """

    def __init__(self, server_name: str, tools_dict: dict, dispatch_dict: dict, system_prompt: str = ""):
        self.server_name = server_name
        self.tools_dict = tools_dict
        self.dispatch_dict = dispatch_dict
        self.system_prompt = system_prompt
        self.mcp_server = self._build_mcp_server()
        self.app = self._build_http_app()

    def _build_mcp_server(self) -> Server:
        """Build MCP protocol server (for stdio)."""
        server = Server(self.server_name)

        @server.list_tools()
        async def list_tools() -> list[Tool]:
            return [
                Tool(name=name, description=meta["description"], inputSchema=meta["schema"])
                for name, meta in self.tools_dict.items()
            ]

        @server.list_resources()
        async def list_resources():
            from mcp.types import Resource

            if self.system_prompt:
                return [Resource(uri="mcp://system_prompt", name="System Prompt", mimeType="text/plain")]
            return []

        @server.read_resource()
        async def read_resource(uri):
            from mcp.types import TextContent as TC

            if uri == "mcp://system_prompt" and self.system_prompt:
                return [TC(type="text", text=self.system_prompt)]
            return []

        @server.call_tool()
        async def call_tool(name: str, arguments: dict | None) -> list[TextContent]:
            args = arguments or {}
            try:
                fn = self.dispatch_dict.get(name)
                if not fn:
                    payload = {"error": "unknown_tool", "tool": name}
                else:
                    payload = fn(args)
            except KeyError as e:
                payload = {"error": "missing_argument", "detail": str(e)}
            except Exception as e:
                payload = {"error": "internal_error", "detail": str(e)}
            return [TextContent(type="text", text=json.dumps(payload, ensure_ascii=False, indent=2))]

        return server

    def _build_http_app(self) -> FastAPI:
        """Build HTTP REST API (for gateway and cross-MCP calls)."""
        app = FastAPI(title=self.server_name, version="1.0.0")

        # ── Health (/health e /v1/health para compatibilidade com registry) ── #
        @app.get("/health")
        @app.get("/v1/health")
        async def health():
            return {"status": "ok", "server": self.server_name}

        # ── Legacy routes (/tools, /tools/call) ─────────────────────────── #
        @app.get("/tools")
        async def list_tools_http():
            tools = [
                {**tool_meta, "name": name}
                for name, tool_meta in self.tools_dict.items()
            ]
            return {"tools": tools}

        @app.post("/tools/call")
        async def call_tool_http(request: dict):
            """Call a tool via HTTP REST (legacy format)."""
            name = request.get("name")
            arguments = request.get("arguments", {})

            if not name:
                raise HTTPException(400, "Missing 'name' in request")

            if name not in self.dispatch_dict:
                raise HTTPException(404, f"Unknown tool: {name}")

            try:
                fn = self.dispatch_dict[name]
                result = fn(arguments)
                return JSONResponse(result)
            except Exception as e:
                raise HTTPException(500, f"Error calling {name}: {str(e)}")

        # ── MCP wrapper routes (/mcp/tools/list, /mcp/tools/call) ─────────── #
        @app.get("/mcp/tools/list")
        async def mcp_list_tools():
            """MCP wrapper-compatible tool discovery endpoint."""
            tools = []
            for name, meta in self.tools_dict.items():
                tools.append({
                    "name": name,
                    "description": meta.get("description", ""),
                    "inputSchema": meta.get("schema", {"type": "object", "properties": {}}),
                })
            return {"result": {"tools": tools}}

        @app.post("/mcp/tools/call")
        async def mcp_call_tool(body: dict):
            """MCP wrapper-compatible tool call endpoint."""
            params = body.get("params", body)
            name = params.get("name", "")
            arguments = params.get("arguments", {})

            fn = self.dispatch_dict.get(name)
            if not fn:
                payload = {"error": "unknown_tool", "tool": name}
            else:
                try:
                    payload = fn(arguments)
                except Exception as e:
                    payload = {"error": "internal_error", "detail": str(e), "tool": name}

            text = json.dumps(payload, ensure_ascii=False, indent=2)
            return {"result": {"content": [{"type": "text", "text": text}]}}

        @app.get("/")
        async def root():
            return {
                "server": self.server_name,
                "endpoints": ["/v1/health", "/mcp/tools/list", "/mcp/tools/call", "/tools", "/tools/call"],
            }

        return app

    async def run(self, http_port: int = 7100):
        """Run both stdio MCP and HTTP server concurrently."""

        async def run_stdio():
            """Run MCP protocol on stdio."""
            try:
                async with stdio_server() as (read_stream, write_stream):
                    await self.mcp_server.run(
                        read_stream, write_stream, self.mcp_server.create_initialization_options()
                    )
            except (EOFError, BrokenPipeError, KeyboardInterrupt):
                pass

        async def run_http():
            """Run HTTP REST API."""
            config = uvicorn.Config(self.app, host="0.0.0.0", port=http_port, log_level="warning")
            server = uvicorn.Server(config)
            await server.serve()

        # Run both concurrently
        await asyncio.gather(
            run_stdio(),
            run_http(),
            return_exceptions=True,
        )


async def run_hybrid_server(server_name: str, tools: dict, dispatch: dict, system_prompt: str = "", http_port: int = 7100):
    """Convenience function to run a hybrid server."""
    server = HybridMCPServer(server_name, tools, dispatch, system_prompt)
    await server.run(http_port)
