"""Regression: the gateway signals a LOGICAL failure via ``result.isError`` on an
HTTP-200 envelope — NOT a top-level JSON-RPC ``error`` and NOT a >=400 status.

Found in the live E2E: the ``health_to_report`` runbook targets ``services-mcp.*``
/ ``qa-mcp.*`` tools that are absent from the real gateway catalog. The gateway
returned ``{"result": {"content": [...], "isError": true}}`` (``tool_not_found``),
but the client only checked the HTTP status and the top-level JSON-RPC ``error``,
so it treated the miss as success and ``approve_and_execute`` reported DONE for a
tool that never ran. The client must raise so the executor marks the item ERROR.

The shared ``_fake_gateway`` is intentionally unfaithful on this path (it returns a
top-level ``error`` the client already caught), which is why the bug slipped past
it — so this file ships its own gateway that mirrors production ``_to_mcp_content``.
"""

from __future__ import annotations

import json

import httpx
import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from app.dev_agent.capability import Capability, CapabilityEnforcer, CapabilityResolver
from app.dev_agent.gateway.client import GatewayError, GatewayToolClient
from app.dev_agent.models.plan import ItemStatus, PlanStatus
from app.dev_agent.plan.builder import PlanBuilder
from app.dev_agent.plan.executor import PlanExecutor
from app.dev_agent.plan.repository import InMemoryPlanRepository
from tests._fake_gateway import StaticTokenProvider


def _faithful_gateway(*, error_tools: set[str]) -> Starlette:
    """ASGI gateway mirroring production ``_to_mcp_content``.

    Success -> ``result.isError=False``; a tool in ``error_tools`` -> **HTTP 200**
    with ``result.isError=True`` (``tool_not_found``), exactly like the live gateway.
    """

    async def _rpc(request: Request) -> JSONResponse:
        body = await request.json()
        req_id = body.get("id")
        if body.get("method") != "tools/call":
            return JSONResponse({"jsonrpc": "2.0", "id": req_id, "result": {"tools": []}})
        name = body.get("params", {}).get("name")
        if name in error_tools:
            text = f"tool_not_found: unknown tool {name!r}"
            # HTTP 200 on purpose — the logical error lives in result.isError.
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {"content": [{"type": "text", "text": text}], "isError": True},
                }
            )
        payload = json.dumps({"status": "healthy", "tool": name})
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"content": [{"type": "text", "text": payload}], "isError": False},
            }
        )

    return Starlette(routes=[Route("/mcp", _rpc, methods=["POST"])])


def _client(app: Starlette) -> GatewayToolClient:
    return GatewayToolClient(
        base_url="http://gateway.local/mcp",
        token_provider=StaticTokenProvider(),
        transport=httpx.ASGITransport(app=app),
    )


@pytest.mark.asyncio
async def test_call_tool_raises_on_iserror_envelope() -> None:
    """result.isError=True (HTTP 200) must raise GatewayError, not return a success."""
    client = _client(_faithful_gateway(error_tools={"qa-mcp.run_tests"}))
    with pytest.raises(GatewayError) as exc:
        await client.call_tool("qa-mcp.run_tests", {}, idempotency_key="k1")
    assert "tool_not_found" in str(exc.value)


@pytest.mark.asyncio
async def test_call_tool_success_envelope_is_returned() -> None:
    """isError=False is returned normally — the fix does not raise on success."""
    client = _client(_faithful_gateway(error_tools=set()))
    out = await client.call_tool("services-mcp.check_health", {}, idempotency_key="k2")
    assert out.get("isError") is False
    assert out.get("content")


@pytest.mark.asyncio
async def test_executor_marks_iserror_item_error_not_phantom_done() -> None:
    """E2E: a runbook tool the gateway rejects -> item ERROR + plan FAILED (no
    phantom DONE), and its dependents are SKIPPED."""
    builder = PlanBuilder(CapabilityResolver())
    plan = builder.build_from_runbook(
        runbook_id="health_to_report",
        session_id="iserror-session",
        inputs_by_task={"check_health": {"service": "api"}, "run_tests": {"suite": "unit"}},
    )
    repo = InMemoryPlanRepository()
    await repo.create(plan)
    # The first runbook tool is rejected by the gateway (isError) — like the live run.
    client = _client(_faithful_gateway(error_tools={"services-mcp.check_health"}))
    enforcer = CapabilityEnforcer(
        {"devops": {Capability.READ}, "qa-engineer": {Capability.READ}}
    )
    executor = PlanExecutor(repo, client, enforcer)
    results = [r async for r in executor.execute(plan, run_id="iserror-run")]

    by_task = {r.task_id: r for r in results}
    assert by_task["check_health"].status is ItemStatus.ERROR
    assert "tool_not_found" in (by_task["check_health"].error or "")
    # Dependents never ran (chained skip), so nothing falsely reports DONE.
    assert by_task["run_tests"].status is ItemStatus.SKIPPED
    assert by_task["generate_report"].status is ItemStatus.SKIPPED

    stored = await repo.load(plan.plan_id)
    assert stored.status is PlanStatus.FAILED
