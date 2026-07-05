"""In-process DEMO gateway — canned successful tool responses, no network/token.

Used by the MCP server when ``DEV_GATEWAY_URL`` is NOT set, so the full
plan -> approve -> execute loop is exercisable in Claude Code Desktop out of the
box (no live platform-mcp, no Twin Token, no LLM). Its shape matches the subset
of :class:`~app.dev_agent.gateway.client.GatewayToolClient` the executor uses.
Point ``DEV_GATEWAY_URL`` at the real gateway to use the real transport instead.
"""

from __future__ import annotations

from typing import Any


class DemoGatewayClient:
    """Duck-typed stand-in for GatewayToolClient (call_tool / list_tools)."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def call_tool(
        self,
        tool: str,
        arguments: dict[str, Any],
        *,
        idempotency_key: str,
        capability: Any = None,
        correlation: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        self.calls.append(tool)
        return {
            "demo": True,
            "tool": tool,
            "capability": str(capability),
            "arguments": arguments,
            "result": f"(demo) executed {tool}",
        }

    async def list_tools(self) -> dict[str, Any]:
        return {"tools": [], "note": "demo gateway — set DEV_GATEWAY_URL for the real catalog"}
