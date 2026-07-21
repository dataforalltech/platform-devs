"""Hybrid MCP server with stdio and canonical HTTP transports."""
from __future__ import annotations

import asyncio
import inspect
import json
import os
from collections.abc import Callable
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool


class HybridMCPServer:
    """Run an MCP protocol server on stdio and a canonical HTTP adapter."""

    def __init__(
        self,
        server_name: str,
        tools_dict: dict[str, dict[str, Any]],
        dispatch_dict: dict[str, Callable[[dict[str, Any]], Any]],
        system_prompt: str = "",
    ) -> None:
        self.server_name = server_name
        self.tools_dict = tools_dict
        self.dispatch_dict = dispatch_dict
        self.system_prompt = system_prompt
        self.mcp_server = self._build_mcp_server()
        self.app = self._build_http_app()

    async def _dispatch(self, name: str, arguments: dict[str, Any]) -> Any:
        function = self.dispatch_dict.get(name)
        if function is None:
            return {"error": "unknown_tool", "tool": name}
        result = function(arguments)
        if inspect.isawaitable(result):
            return await result
        return result

    def _build_mcp_server(self) -> Server:
        server = Server(self.server_name)

        @server.list_tools()
        async def list_tools() -> list[Tool]:
            return [
                Tool(
                    name=name,
                    description=meta["description"],
                    inputSchema=meta["schema"],
                )
                for name, meta in self.tools_dict.items()
            ]

        @server.list_resources()
        async def list_resources():
            from mcp.types import Resource

            if self.system_prompt:
                return [
                    Resource(
                        uri="mcp://system_prompt",
                        name="System Prompt",
                        mimeType="text/plain",
                    )
                ]
            return []

        @server.read_resource()
        async def read_resource(uri):
            from mcp.types import TextContent as ResourceTextContent

            if uri == "mcp://system_prompt" and self.system_prompt:
                return [ResourceTextContent(type="text", text=self.system_prompt)]
            return []

        @server.call_tool()
        async def call_tool(
            name: str, arguments: dict[str, Any] | None
        ) -> list[TextContent]:
            try:
                payload = await self._dispatch(name, arguments or {})
            except KeyError as exc:
                payload = {"error": "missing_argument", "detail": str(exc)}
            except Exception:
                payload = {"error": "internal_error", "tool": name}
            return [
                TextContent(
                    type="text",
                    text=json.dumps(payload, ensure_ascii=False, indent=2),
                )
            ]

        return server

    def _build_http_app(self) -> FastAPI:
        app = FastAPI(title=self.server_name, version="1.0.0")
        legacy_routes_enabled = (
            os.getenv("MCP_ENABLE_LEGACY_ROUTES") == "1"
            and os.getenv("ENV_PROFILE", "").startswith("local-")
        )

        @app.get("/v1/health")
        @app.get("/v1/health/live")
        @app.get("/v1/health/ready")
        async def health():
            return {"status": "ok", "server": self.server_name}

        async def legacy_list_tools():
            return {
                "tools": [
                    {**tool_meta, "name": name}
                    for name, tool_meta in self.tools_dict.items()
                ]
            }

        async def legacy_call_tool(request: dict[str, Any]):
            name = request.get("name")
            if not name:
                raise HTTPException(400, "Missing 'name' in request")
            if name not in self.dispatch_dict:
                raise HTTPException(404, f"Unknown tool: {name}")
            try:
                return JSONResponse(
                    await self._dispatch(name, request.get("arguments", {}))
                )
            except Exception as exc:
                raise HTTPException(500, "Internal tool execution error") from exc

        if legacy_routes_enabled:
            app.add_api_route("/health", health, methods=["GET"])
            app.add_api_route("/tools", legacy_list_tools, methods=["GET"])
            app.add_api_route("/tools/call", legacy_call_tool, methods=["POST"])

        @app.get("/mcp/tools/list")
        async def mcp_list_tools():
            tools = [
                {
                    "name": name,
                    "description": meta.get("description", ""),
                    "inputSchema": meta.get(
                        "schema", {"type": "object", "properties": {}}
                    ),
                }
                for name, meta in self.tools_dict.items()
            ]
            return {"result": {"tools": tools}}

        @app.post("/mcp/tools/call")
        async def mcp_call_tool(body: dict[str, Any]):
            params = body.get("params", body)
            name = params.get("name", "")
            try:
                payload = await self._dispatch(name, params.get("arguments", {}))
            except Exception:
                payload = {"error": "internal_error", "tool": name}
            return {
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(
                                payload, ensure_ascii=False, indent=2
                            ),
                        }
                    ]
                }
            }

        @app.get("/")
        async def root():
            endpoints = [
                "/v1/health/live",
                "/v1/health/ready",
                "/mcp/tools/list",
                "/mcp/tools/call",
            ]
            if legacy_routes_enabled:
                endpoints.extend(["/health", "/tools", "/tools/call"])
            return {"server": self.server_name, "endpoints": endpoints}

        return app

    async def run(self, http_port: int = 7100) -> None:
        async def run_stdio() -> None:
            try:
                async with stdio_server() as (read_stream, write_stream):
                    await self.mcp_server.run(
                        read_stream,
                        write_stream,
                        self.mcp_server.create_initialization_options(),
                    )
            except (EOFError, BrokenPipeError, KeyboardInterrupt):
                pass

        async def run_http() -> None:
            config = uvicorn.Config(
                self.app,
                host="0.0.0.0",
                port=http_port,
                log_level="warning",
            )
            await uvicorn.Server(config).serve()

        await asyncio.gather(run_stdio(), run_http())


async def run_hybrid_server(
    server_name: str,
    tools: dict[str, dict[str, Any]],
    dispatch: dict[str, Callable[[dict[str, Any]], Any]],
    system_prompt: str = "",
    http_port: int = 7100,
) -> None:
    """Run a configured hybrid server."""
    await HybridMCPServer(server_name, tools, dispatch, system_prompt).run(http_port)
