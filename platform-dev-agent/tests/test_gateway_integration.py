"""Integration skeleton — hits ONE real read tool via the gateway.

Skipped unless ``DEV_GATEWAY_URL`` is set in the environment. This is the
step-2 proof from the walking skeleton: OAuth + Streamable HTTP + parsing of
``result``, isolated, before any orchestration.

Auth: provide an OAuth token via ``DEV_GATEWAY_TOKEN`` (a static bearer token
is enough to prove transport). A real deployment would swap in a proper OAuth
client-credentials provider.
"""

from __future__ import annotations

import os

import pytest

from app.dev_agent.gateway.client import GatewayToolClient, build_correlation
from app.dev_agent.models.plan import Capability

pytestmark = pytest.mark.skipif(
    not os.getenv("DEV_GATEWAY_URL"),
    reason="DEV_GATEWAY_URL not set; skipping live gateway integration test",
)


class _StaticTokenProvider:
    """Minimal async token provider backed by an env var."""

    def __init__(self, token: str) -> None:
        self._token = token

    async def get_token(self) -> str:
        return self._token


@pytest.mark.asyncio
async def test_call_one_real_read_tool() -> None:
    base_url = os.environ["DEV_GATEWAY_URL"]
    token = os.getenv("DEV_GATEWAY_TOKEN", "")
    tool = os.getenv("DEV_GATEWAY_READ_TOOL", "services-mcp.list_services")

    client = GatewayToolClient(
        base_url=base_url,
        token_provider=_StaticTokenProvider(token),
    )
    result = await client.call_tool(
        tool,
        {},
        idempotency_key="itest-read-1",
        capability=Capability.READ,
        correlation=build_correlation(
            run_id="itest-run",
            session_id="itest-session",
            agent_profile="qa-engineer",
        ),
    )
    # We only prove transport + parse here, not the tool's payload shape.
    assert result is not None
