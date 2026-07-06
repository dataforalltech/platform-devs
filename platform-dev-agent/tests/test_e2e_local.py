"""First autonomous E2E — the whole chain over the real httpx transport.

RUNBOOK_CATALOG -> PlanBuilder -> InMemoryPlanRepository -> PlanExecutor ->
GatewayToolClient (real httpx, ASGITransport -> fake gateway) -> fake gateway.

This is the walking-skeleton milestone (critique §3, step 6): a single read-only
runbook executes end-to-end, proving transport (real JSON-RPC), persistence
(guarded transitions), and the executor loop — with NO approval and NO write.

The JSON-RPC really goes over httpx: only the transport is swapped for an
in-process ASGI transport so no socket is opened. Everything else — envelope,
headers, Idempotency-Key, retry policy, result parsing — is the production path.

--------------------------------------------------------------------------------
Pointing this at the REAL gateway (no code change to the components):
  * set base_url = os.environ["DEV_GATEWAY_URL"]  (the live gateway endpoint);
  * DROP the injected `transport=` so httpx opens a real socket;
  * swap StaticTokenProvider for a real OAuth 2.1 token provider (get_token()).
The `test_e2e_against_real_gateway` variant below does exactly that and is
skipped unless DEV_GATEWAY_URL is set.
--------------------------------------------------------------------------------
"""

from __future__ import annotations

import os

import httpx
import pytest

from app.dev_agent.capability import Capability, CapabilityEnforcer, CapabilityResolver
from app.dev_agent.gateway.client import GatewayToolClient
from app.dev_agent.models.plan import ItemStatus, PlanStatus
from app.dev_agent.plan.builder import PlanBuilder
from app.dev_agent.plan.executor import PlanExecutor
from app.dev_agent.plan.repository import InMemoryPlanRepository
from app.dev_agent.runbook.catalog import RUNBOOK_CATALOG
from tests._fake_gateway import FakeGateway, StaticTokenProvider


@pytest.mark.asyncio
async def test_e2e_local_read_pipeline_all_done() -> None:
    # 1) The catalog runbook (the only one in the walking skeleton).
    assert "health_to_report" in RUNBOOK_CATALOG

    # 2) Build the plan from the runbook (topo-sort, capability/risk, validation).
    builder = PlanBuilder(CapabilityResolver())
    plan = builder.build_from_runbook(
        runbook_id="health_to_report",
        session_id="e2e-session",
        inputs_by_task={
            "check_health": {"service": "api"},
            "run_tests": {"suite": "unit"},
        },
    )
    assert plan.status is PlanStatus.PENDING
    assert [i.task_id for i in plan.items] == [
        "check_health",
        "run_tests",
        "generate_report",
    ]

    # 3) Persist it.
    repo = InMemoryPlanRepository()
    await repo.create(plan)

    # 4) Real GatewayToolClient over real httpx, transport -> in-process gateway.
    fake = FakeGateway()
    client = GatewayToolClient(
        base_url="http://gateway.local/mcp",
        token_provider=StaticTokenProvider(),
        transport=httpx.ASGITransport(app=fake.app),
    )

    # 5) Enforcer ON (read-only profiles are enough for the read runbook).
    enforcer = CapabilityEnforcer(
        {"devops": {Capability.READ}, "qa-engineer": {Capability.READ}}
    )

    # 6) Execute the whole plan (no approval gate: approved_item_ids=None).
    executor = PlanExecutor(repo, client, enforcer)
    results = [r async for r in executor.execute(plan, run_id="e2e-run")]

    # Assert: all 3 DONE, final status DONE.
    assert len(results) == 3
    assert [r.status for r in results] == [ItemStatus.DONE] * 3

    stored = await repo.load(plan.plan_id)
    assert stored.status is PlanStatus.DONE
    assert all(i.status is ItemStatus.DONE for i in stored.items)

    # The transport really carried JSON-RPC tools/call for all three tools,
    # each with its own non-empty Idempotency-Key.
    called_tools = [tool for tool, _ in fake.idempotency_keys]
    assert called_tools == [
        "services-mcp.check_health",
        "qa-mcp.run_unit_tests",
        "qa-mcp.generate_qa_report",
    ]
    assert all(key for _, key in fake.idempotency_keys)


@pytest.mark.skipif(
    not os.getenv("DEV_GATEWAY_URL"),
    reason="DEV_GATEWAY_URL not set; skipping E2E against the real gateway",
)
@pytest.mark.asyncio
async def test_e2e_against_real_gateway() -> None:
    """Same chain, but against the REAL gateway (no injected transport).

    Enable by setting DEV_GATEWAY_URL (and DEV_GATEWAY_TOKEN for a bearer token).
    Notes for the real gateway (see docs/REAL_GATEWAY_E2E.md):
      * DEV_GATEWAY_URL must be the JSON-RPC endpoint, i.e. end in ``/mcp``
        (not ``/mcp/tools/call``, which is the REST alias with a different body);
      * DEV_TENANT_ID is REQUIRED — the gateway rejects calls without X-Tenant-Id;
      * DEV_GATEWAY_TOKEN must be a Twin Token (aud=mcp:gateway).
    Swap StaticTokenProvider for a real OAuth 2.1 provider in a deployment.
    """
    builder = PlanBuilder(CapabilityResolver())
    plan = builder.build_from_runbook(
        runbook_id="health_to_report",
        session_id="e2e-real-session",
        inputs_by_task={
            "check_health": {"service": "api"},
            "run_tests": {"suite": "unit"},
        },
    )
    repo = InMemoryPlanRepository()
    await repo.create(plan)

    client = GatewayToolClient(
        base_url=os.environ["DEV_GATEWAY_URL"],  # real endpoint
        token_provider=StaticTokenProvider(os.getenv("DEV_GATEWAY_TOKEN", "")),
        # The REAL gateway requires X-Tenant-Id on EVERY request (SEC-035); the
        # client stamps it on all of them (incl. tools/list) when tenant_id is set.
        tenant_id=os.getenv("DEV_TENANT_ID"),
        # NOTE: no transport= here -> httpx opens a real socket to the gateway.
    )
    enforcer = CapabilityEnforcer(
        {"devops": {Capability.READ}, "qa-engineer": {Capability.READ}}
    )
    executor = PlanExecutor(repo, client, enforcer)
    results = [
        r
        async for r in executor.execute(
            plan, run_id="e2e-real-run", tenant_id=os.getenv("DEV_TENANT_ID")
        )
    ]

    stored = await repo.load(plan.plan_id)
    assert stored.status in (PlanStatus.DONE, PlanStatus.PARTIAL)
    assert len(results) == 3
