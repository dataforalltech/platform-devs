from __future__ import annotations

import httpx
import pytest

from shared.mcp_client import MCPClientError, MCPHttpClient, MCPToolError


def test_python_client_calls_only_the_canonical_gateway() -> None:
    observed = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["url"] = str(request.url)
        observed["authorization"] = request.headers["authorization"]
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {"observed": True}})

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as http_client:
        client = MCPHttpClient("http://gateway", "opaque-token", client=http_client)
        assert client.call("contracts-mcp", "contracts_list", {}) == {"observed": True}
    assert observed == {
        "url": "http://gateway/mcp/contracts-mcp/tools/call",
        "authorization": "Bearer opaque-token",
    }


def test_python_client_never_converts_errors_to_success() -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200, json={"jsonrpc": "2.0", "id": 1, "error": {"code": -32603, "message": "failed"}}
        )
    )
    with httpx.Client(transport=transport) as http_client:
        client = MCPHttpClient("http://gateway", "opaque-token", client=http_client)
        with pytest.raises(MCPToolError, match="failed"):
            client.call("contracts-mcp", "contracts_list")

    failing = httpx.MockTransport(lambda _request: httpx.Response(503))
    with httpx.Client(transport=failing) as http_client:
        client = MCPHttpClient("http://gateway", "opaque-token", client=http_client)
        with pytest.raises(MCPClientError, match="HTTP 503"):
            client.call("contracts-mcp", "contracts_list")
