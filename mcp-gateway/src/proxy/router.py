"""Proxy router — routes requests to internal MCP servers."""
from __future__ import annotations

import time
from fastapi import FastAPI, HTTPException, Header, Request
import httpx
import json

from src.auth.token_validator import authenticate_request
from src.auth.rbac import is_authorized
from src.middleware.rate_limiter import check_rate_limit
from src.middleware.audit_logger import log_tool_call

MCP_REGISTRY = {
    "qazilla-mcp": "http://qazilla-mcp:7100",
    "backzilla-mcp": "http://backzilla-mcp:7100",
    "archzilla-mcp": "http://archzilla-mcp:7100",
    "seczilla-mcp": "http://seczilla-mcp:7100",
    "opszilla-mcp": "http://opszilla-mcp:7100",
    "productzilla-mcp": "http://productzilla-mcp:7100",
    "frontzilla-mcp": "http://frontzilla-mcp:7100",
    "pozilla-mcp": "http://pozilla-mcp:7100",
}

async def _get_user_or_fail(authorization: str | None):
    """Extract user from auth header, fail if not authorized."""
    user = await authenticate_request(authorization)
    if not user:
        raise HTTPException(403, "Unauthorized")
    return user

def setup_proxy_routes(app: FastAPI):
    """Add proxy routes to FastAPI app."""

    @app.get("/mcp")
    async def list_mcps():
        """List all available MCPs."""
        return {
            "mcps": [
                {
                    "name": name,
                    "url": url,
                    "status": "available",
                }
                for name, url in MCP_REGISTRY.items()
            ]
        }

    @app.get("/mcp/{mcp_name}/tools")
    async def list_tools(mcp_name: str, authorization: str | None = Header(None)):
        """List tools available on an MCP."""
        user = await _get_user_or_fail(authorization)

        if mcp_name not in MCP_REGISTRY:
            raise HTTPException(404, f"MCP not found: {mcp_name}")

        mcp_url = MCP_REGISTRY[mcp_name]
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.get(f"{mcp_url}/tools", timeout=10)
                resp.raise_for_status()
                return resp.json()
            except Exception as e:
                raise HTTPException(503, f"Failed to fetch tools: {str(e)}")

    @app.post("/mcp/{mcp_name}/tools/call")
    async def call_tool(
        mcp_name: str,
        http_request: Request,
        request: dict,
        authorization: str | None = Header(None),
    ):
        """Call a tool on an MCP."""
        start_time = time.time()
        user = await _get_user_or_fail(authorization)

        # Check rate limits
        await check_rate_limit(user.user_id, user.role)

        if mcp_name not in MCP_REGISTRY:
            raise HTTPException(404, f"MCP not found: {mcp_name}")

        tool_name = request.get("name")
        if not tool_name:
            raise HTTPException(400, "Missing 'name' in request")

        if not is_authorized(user, mcp_name, tool_name):
            await log_tool_call(
                user_id=user.user_id,
                role=user.role,
                tenant_id=user.tenant_id,
                mcp=mcp_name,
                tool=tool_name,
                arguments=request.get("arguments", {}),
                result={"error": "forbidden"},
                duration_ms=int((time.time() - start_time) * 1000),
                status="forbidden",
                client_ip=http_request.client.host if http_request.client else "unknown",
                user_agent=http_request.headers.get("user-agent", ""),
            )
            raise HTTPException(403, f"Not authorized to call {tool_name} on {mcp_name}")

        mcp_url = MCP_REGISTRY[mcp_name]
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(
                    f"{mcp_url}/tools/call",
                    json=request,
                    timeout=30,
                )
                resp.raise_for_status()
                result = resp.json()
                duration_ms = int((time.time() - start_time) * 1000)

                # Log successful call
                await log_tool_call(
                    user_id=user.user_id,
                    role=user.role,
                    tenant_id=user.tenant_id,
                    mcp=mcp_name,
                    tool=tool_name,
                    arguments=request.get("arguments", {}),
                    result=result,
                    duration_ms=duration_ms,
                    status="success",
                    client_ip=http_request.client.host if http_request.client else "unknown",
                    user_agent=http_request.headers.get("user-agent", ""),
                )
                return result
            except httpx.HTTPStatusError as e:
                await log_tool_call(
                    user_id=user.user_id,
                    role=user.role,
                    tenant_id=user.tenant_id,
                    mcp=mcp_name,
                    tool=tool_name,
                    arguments=request.get("arguments", {}),
                    result={"error": e.response.text},
                    duration_ms=int((time.time() - start_time) * 1000),
                    status="error",
                    client_ip=http_request.client.host if http_request.client else "unknown",
                    user_agent=http_request.headers.get("user-agent", ""),
                )
                raise HTTPException(e.response.status_code, e.response.text)
            except Exception as e:
                await log_tool_call(
                    user_id=user.user_id,
                    role=user.role,
                    tenant_id=user.tenant_id,
                    mcp=mcp_name,
                    tool=tool_name,
                    arguments=request.get("arguments", {}),
                    result={"error": str(e)},
                    duration_ms=int((time.time() - start_time) * 1000),
                    status="error",
                    client_ip=http_request.client.host if http_request.client else "unknown",
                    user_agent=http_request.headers.get("user-agent", ""),
                )
                raise HTTPException(503, f"Failed to call tool: {str(e)}")

    @app.get("/admin/quotas")
    async def admin_quotas(authorization: str | None = Header(None)):
        """Get quota usage (admin only)."""
        user = await _get_user_or_fail(authorization)
        if user.role != "admin":
            raise HTTPException(403, "Admin only")

        # TODO: Return actual quota data from Redis
        return {"quotas": {}}
