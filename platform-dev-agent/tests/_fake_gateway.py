"""A minimal ASGI fake of the platform-mcp gateway (JSON-RPC over HTTP).

Implements just enough of ``tools/list`` and ``tools/call`` to exercise the
:class:`GatewayToolClient` over the *real* httpx stack (via
``httpx.ASGITransport(app=...)``) without opening a socket. Returns canned
results for the three read tools of the walking-skeleton runbook and records the
``Idempotency-Key`` header seen on each call (proves the client always sends it).

This is a Starlette app (added to the project's dev dependencies) — it speaks the
same JSON-RPC envelope the production gateway does, so the client code under test
is unchanged.
"""

from __future__ import annotations

from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

# Canned results per read tool of the health_to_report runbook.
_CANNED: dict[str, dict[str, Any]] = {
    "services-mcp.check_health": {"status": "healthy", "service": "api"},
    "qa-mcp.run_tests": {"passed": 42, "failed": 0, "suite": "unit"},
    "qa-mcp.generate_report": {"report_url": "memory://qa-report", "format": "md"},
}


class FakeGateway:
    """Callable holder so a test can inspect the idempotency keys received."""

    def __init__(self) -> None:
        # Ordered log of (tool, idempotency_key) as calls arrive.
        self.idempotency_keys: list[tuple[str, str]] = []
        self.app = Starlette(routes=[Route("/mcp", self._rpc, methods=["POST"])])

    async def _rpc(self, request: Request) -> JSONResponse:
        body = await request.json()
        method = body.get("method")
        req_id = body.get("id")

        if method == "tools/list":
            tools = [{"name": name} for name in _CANNED]
            return JSONResponse({"jsonrpc": "2.0", "id": req_id, "result": {"tools": tools}})

        if method == "tools/call":
            params = body.get("params", {})
            name = params.get("name")
            idem = request.headers.get("idempotency-key", "")
            self.idempotency_keys.append((name, idem))
            if name not in _CANNED:
                return JSONResponse(
                    {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "error": {"code": -32601, "message": f"unknown tool {name!r}"},
                    }
                )
            return JSONResponse(
                {"jsonrpc": "2.0", "id": req_id, "result": dict(_CANNED[name])}
            )

        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"unknown method {method!r}"},
            }
        )


class StaticTokenProvider:
    """Minimal async token provider (fake OAuth) for tests."""

    def __init__(self, token: str = "fake-token") -> None:
        self._token = token

    async def get_token(self) -> str:
        return self._token
