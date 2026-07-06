"""HTTP sidecar for platform-iceberg MCP (Starlette + Uvicorn)."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

if TYPE_CHECKING:
    from mcp import FastMCP

logger = logging.getLogger("iceberg_mcp.sidecar")


class MCPHttpSidecar:
    """Wraps a FastMCP instance in an HTTP server."""

    def __init__(self, mcp_instance: "FastMCP", port: int = 7104) -> None:
        self._mcp = mcp_instance
        self._port = port
        self._app = Starlette(routes=self._routes())

    def _routes(self) -> list[Route]:
        return [
            Route("/health", self._health, methods=["GET"]),
            Route("/mcp/tools/list", self._tools_list, methods=["GET"]),
            Route("/mcp/tools/call", self._tools_call, methods=["POST"]),
        ]

    async def _health(self, request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "service": self._mcp.name})

    async def _tools_list(self, request: Request) -> JSONResponse:
        tools = []
        for tool in self._mcp._tool_manager.list_tools():
            tools.append(
                {
                    "name": tool.name,
                    "description": tool.description,
                    "inputSchema": tool.parameters,
                }
            )
        return JSONResponse({"tools": tools})

    async def _tools_call(self, request: Request) -> JSONResponse:
        try:
            body: dict[str, Any] = await request.json()
        except Exception:
            return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

        tool_name: str = body.get("name", "")
        arguments: dict[str, Any] = body.get("arguments", {})

        # Inject tenant_id from X-Tenant-Id header if not provided
        if "tenant_id" not in arguments:
            tenant_header = request.headers.get("X-Tenant-Id")
            if tenant_header:
                arguments["tenant_id"] = tenant_header

        # Verify auth if token verifier is configured
        verifier = getattr(self._mcp, "_token_verifier", None)
        claims = None
        if verifier is not None:
            auth = request.headers.get("Authorization", "")
            token = auth.removeprefix("Bearer ").strip()
            if token:
                claims = verifier.verify(token)
            if claims is None and verifier is not None:
                from iceberg_mcp.governance import EXEMPT_TOOLS
                if tool_name not in EXEMPT_TOOLS:
                    return JSONResponse({"error": "Unauthorized"}, status_code=401)

        # Governance enforcement (opt-in)
        try:
            from iceberg_mcp.governance import enforce_tool
            enforce_tool(tool_name, arguments, claims)
        except PermissionError as exc:
            return JSONResponse({"error": str(exc)}, status_code=403)

        try:
            result = await self._mcp.call_tool(tool_name, arguments)
            return JSONResponse({"result": result})
        except Exception as exc:
            logger.exception("Error calling tool %s", tool_name)
            return JSONResponse({"error": str(exc)}, status_code=500)

    async def serve(self) -> None:
        import uvicorn

        config = uvicorn.Config(
            self._app,
            host="0.0.0.0",
            port=self._port,
            log_level="info",
        )
        server = uvicorn.Server(config)
        await server.serve()
