"""Fail-closed client for cross-MCP calls through the canonical gateway."""

from __future__ import annotations

import os
import re
from typing import Any

import httpx

_SERVICE_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_TOOL_NAME = re.compile(r"^[a-z][a-z0-9_-]*$")


class MCPClientError(RuntimeError):
    """A gateway transport or protocol failure."""


class MCPToolError(MCPClientError):
    """A tool returned a canonical JSON-RPC error."""


class MCPHttpClient:
    """Call governed tools without direct provider URLs or local fallbacks."""

    def __init__(
        self,
        gateway_url: str | None = None,
        access_token: str | None = None,
        *,
        timeout: float = 30.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.gateway_url = (gateway_url or os.environ.get("MCP_GATEWAY_URL", "")).rstrip("/")
        self._access_token = access_token or os.environ.get("MCP_GATEWAY_TOKEN", "")
        if not self.gateway_url:
            raise MCPClientError("MCP_GATEWAY_URL is required")
        if not self._access_token:
            raise MCPClientError("MCP_GATEWAY_TOKEN is required")
        self._owns_client = client is None
        self.client = client or httpx.Client(timeout=timeout)
        self._request_id = 0

    def call(self, service: str, tool: str, args: dict[str, Any] | None = None) -> Any:
        if not _SERVICE_ID.fullmatch(service):
            raise MCPClientError("invalid MCP service id")
        if not _TOOL_NAME.fullmatch(tool):
            raise MCPClientError("invalid MCP tool name")
        self._request_id += 1
        try:
            response = self.client.post(
                f"{self.gateway_url}/mcp/{service}/tools/call",
                headers={"Authorization": f"Bearer {self._access_token}"},
                json={"id": self._request_id, "name": tool, "arguments": args or {}},
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.TimeoutException as exc:
            raise MCPClientError("MCP gateway request timed out") from exc
        except httpx.HTTPStatusError as exc:
            raise MCPClientError(f"MCP gateway returned HTTP {exc.response.status_code}") from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise MCPClientError("MCP gateway request failed") from exc
        if not isinstance(payload, dict):
            raise MCPClientError("MCP gateway returned a non-object response")
        error = payload.get("error")
        if isinstance(error, dict):
            raise MCPToolError(str(error.get("message") or "MCP tool returned an error"))
        if "result" not in payload:
            raise MCPClientError("MCP gateway response has no result")
        return payload["result"]

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def __enter__(self) -> "MCPHttpClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


_client: MCPHttpClient | None = None


def get_mcp_client() -> MCPHttpClient:
    global _client
    if _client is None:
        _client = MCPHttpClient()
    return _client
