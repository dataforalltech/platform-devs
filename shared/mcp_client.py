"""Shared MCP HTTP Client for cross-MCP calls in Zillas."""
import httpx
import json
from typing import Any


class MCPHttpClient:
    """HTTP client for calling tools from other MCP services."""

    BASE_URLS = {
        "qa-mcp": "http://qa-mcp:7109",
        "docs-mcp": "http://docs-mcp:7111",
        "infra-mcp": "http://infra-mcp:7106",
        "test-mcp": "http://test-mcp:7117",
        "ai-governance-mcp": "http://ai-governance-mcp:7112",
        "session-mcp": "http://session-mcp:7102",
    }

    def __init__(self, timeout: float = 10.0):
        self.timeout = timeout
        self.client = httpx.Client(timeout=timeout)

    def call(self, service: str, tool: str, args: dict | None = None) -> dict[str, Any]:
        """Call a tool on another MCP service.

        Args:
            service: Service name (key in BASE_URLS)
            tool: Tool name to invoke
            args: Arguments to pass to the tool

        Returns:
            Tool response as dict
        """
        base = self.BASE_URLS.get(service)
        if not base:
            return {"error": f"Unknown service: {service}"}

        try:
            resp = self.client.post(
                f"{base}/tools/call",
                json={"name": tool, "arguments": args or {}},
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as e:
            return {"error": f"HTTP error calling {service}/{tool}: {str(e)}"}
        except json.JSONDecodeError as e:
            return {"error": f"Invalid JSON response from {service}/{tool}: {str(e)}"}
        except Exception as e:
            return {"error": f"Error calling {service}/{tool}: {str(e)}"}

    def close(self):
        """Close the HTTP client."""
        self.client.close()


# Global client instance
_client: MCPHttpClient | None = None


def get_mcp_client() -> MCPHttpClient:
    """Get or create the global MCP HTTP client."""
    global _client
    if _client is None:
        _client = MCPHttpClient()
    return _client
