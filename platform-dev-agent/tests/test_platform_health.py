"""The ``platform_health`` runbook — wired to tools that EXIST in the live gateway.

Unlike ``health_to_report`` (services-mcp/qa-mcp, not yet registered on the current
gateway), every tool here is in the catalog and takes no args, so the pipeline is
genuinely GREEN against the real gateway. This test runs it over the real httpx
stack against the in-process fake gateway (same envelope as production), and checks
the selector routes ``platform_health`` to it.
"""

from __future__ import annotations

import httpx
import pytest

from app.dev_agent.capability import Capability, CapabilityEnforcer, CapabilityResolver
from app.dev_agent.gateway.client import GatewayToolClient
from app.dev_agent.models.plan import ItemStatus, PlanStatus, RiskLevel
from app.dev_agent.plan.builder import PlanBuilder
from app.dev_agent.plan.executor import PlanExecutor
from app.dev_agent.plan.repository import InMemoryPlanRepository
from app.dev_agent.runbook.catalog import RUNBOOK_CATALOG
from app.dev_agent.runbook_selector import RunbookSelector
from tests._fake_gateway import FakeGateway, StaticTokenProvider


def test_selector_routes_to_platform_health() -> None:
    sel = RunbookSelector()
    assert sel.select(intent="", entity_type="platform_health", sub_intent="") == "platform_health"
    assert "platform_health" in RUNBOOK_CATALOG


@pytest.mark.asyncio
async def test_platform_health_pipeline_all_done() -> None:
    # Build the plan from the runbook (no inputs — every tool takes no args).
    builder = PlanBuilder(CapabilityResolver())
    plan = builder.build_from_runbook(
        runbook_id="platform_health",
        session_id="ph-session",
        inputs_by_task={},  # health checks take {}; nothing to inject
    )
    assert [i.task_id for i in plan.items] == ["admin_health", "auth_health", "list_tenants"]
    # All read, low risk -> no approval gate needed.
    assert all(i.capability is Capability.READ for i in plan.items)
    assert all(i.risk is RiskLevel.LOW for i in plan.items)

    repo = InMemoryPlanRepository()
    await repo.create(plan)

    fake = FakeGateway()
    client = GatewayToolClient(
        base_url="http://gateway.local/mcp",
        token_provider=StaticTokenProvider(),
        transport=httpx.ASGITransport(app=fake.app),
    )
    enforcer = CapabilityEnforcer(
        {"devops": {Capability.READ}, "qa-engineer": {Capability.READ}}
    )
    executor = PlanExecutor(repo, client, enforcer)
    results = [r async for r in executor.execute(plan, run_id="ph-run")]

    assert [r.status for r in results] == [ItemStatus.DONE] * 3
    stored = await repo.load(plan.plan_id)
    assert stored.status is PlanStatus.DONE

    # The transport really carried tools/call for the REAL gateway tool ids.
    called = [tool for tool, _ in fake.idempotency_keys]
    assert called == [
        "admin.admin_health_check",
        "auth.auth_health_check",
        "auth.auth_list_tenants",
    ]
