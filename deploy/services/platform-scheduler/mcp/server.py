"""platform-scheduler MCP sidecar (DTR standard).

Thin FastAPI HTTP bridge over the scheduler REST API for the Digital Twin gateway:
  GET  /v1/health        — liveness
  GET  /mcp/tools/list   — {"result": {"tools": [...]}}
  POST /mcp/tools/call   — {"params": {"name", "arguments"}} -> {"result": {"content": [...]}}

Every tools/call runs the per-service Twin PEP (verify inner Twin Token aud mcp:scheduler +
PDP + write-gate) BEFORE dispatching to the scheduler API (defense in depth, INV-1). Tenant
from signed claims (else X-Tenant-Id header). Health exempt.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request

from .catalog import TOOLS, resolve_path
from .governance import enforce_tool

_log = logging.getLogger("scheduler_mcp")

_BASE = os.environ.get("SCHEDULER_MCP_SERVICE_BASE_URL", "http://scheduler:8000").rstrip("/")
_INTERNAL_TOKEN = os.environ.get("SCHEDULER_MCP_INTERNAL_API_TOKEN", "")
_TIMEOUT = float(os.environ.get("SCHEDULER_MCP_REQUEST_TIMEOUT", "15"))


def _dispatch(name: str, args: dict[str, Any], tenant_id: str) -> dict[str, Any]:
    spec = TOOLS.get(name)
    if spec is None:
        return {"error": "UnknownTool", "tool": name}
    path, rest = resolve_path(spec["path"], args)
    rest.pop("tenant_id", None)
    method = spec["method"].upper()
    headers = {"Content-Type": "application/json", "X-Tenant-Id": str(tenant_id)}
    if _INTERNAL_TOKEN:
        headers["X-Internal-Token"] = _INTERNAL_TOKEN
    body = rest.get("body") if "body" in rest else (rest or None)
    try:
        with httpx.Client(timeout=_TIMEOUT) as c:
            resp = c.request(method, f"{_BASE}{path}", json=body if method != "GET" else None,
                             params=rest if method == "GET" else None, headers=headers)
        try:
            data = resp.json()
        except Exception:  # noqa: BLE001
            data = {"raw": resp.text}
        return {"status_code": resp.status_code, "data": data}
    except Exception as exc:  # noqa: BLE001
        return {"error": "backend_unreachable", "detail": str(exc), "tool": name}


def build_app() -> FastAPI:
    app = FastAPI(title="platform-scheduler-mcp", docs_url="/docs")

    @app.get("/v1/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "service": "scheduler-mcp", "tools": len(TOOLS)}

    @app.get("/")
    def root() -> dict[str, str]:
        return {"service": "scheduler-mcp", "health": "/v1/health"}

    @app.get("/mcp/tools/list")
    def http_list_tools() -> dict[str, Any]:
        tools = [{"name": n, "description": s["description"], "inputSchema": s["inputSchema"]}
                 for n, s in TOOLS.items()]
        return {"result": {"tools": tools}}

    @app.post("/mcp/tools/call")
    async def http_call_tool(request: Request) -> dict[str, Any]:
        body = await request.json()
        params = body.get("params", body)
        name = params.get("name", "")
        args = dict(params.get("arguments", {}) or {})
        try:
            claims = await enforce_tool(request, name, args)
        except Exception as exc:  # noqa: BLE001
            code = type(exc).__name__
            if code == "PolicyDenied":
                raise HTTPException(status_code=403, detail=str(exc)) from exc
            if code == "TwinTokenError":
                raise HTTPException(status_code=401, detail=str(exc),
                                    headers={"WWW-Authenticate": "Bearer"}) from exc
            raise
        tenant_id = getattr(claims, "tenant_id", None) or request.headers.get("X-Tenant-Id", "1")
        payload = _dispatch(name, args, str(tenant_id))
        return {"result": {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}]}}

    return app


app = build_app()


def main() -> None:
    import uvicorn

    port = int(os.getenv("MCP_PORT", "7106"))
    _log.info("scheduler_mcp_ready port=%d base=%s tools=%d", port, _BASE, len(TOOLS))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")


if __name__ == "__main__":
    main()
