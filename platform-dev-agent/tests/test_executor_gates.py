"""Executor tests for the approval gates (N1/N2) and the run budget.

Synthetic plans (NOT the read-only runbook) so we can place a HIGH-risk item and
drive the N2 gate, plus a multi-item read plan to trip the tool-call budget
mid-run. Both prove the run stops CLEANLY: skipped items are reported, the plan
still reaches a terminal status, and nothing escapes the generator.
"""

from __future__ import annotations

import httpx
import pytest

from app.dev_agent.budget import RunBudget
from app.dev_agent.capability import CapabilityEnforcer
from app.dev_agent.gateway.client import GatewayToolClient
from app.dev_agent.models.plan import (
    Capability,
    ItemStatus,
    Plan,
    PlanItem,
    PlanStatus,
    RiskLevel,
)
from app.dev_agent.plan.approval import ApprovalDecision, ApprovalGate
from app.dev_agent.plan.executor import PlanExecutor
from app.dev_agent.plan.repository import InMemoryPlanRepository
from tests._fake_gateway import FakeGateway, StaticTokenProvider


def _client(fake: FakeGateway) -> GatewayToolClient:
    return GatewayToolClient(
        base_url="http://gateway.test/mcp",
        token_provider=StaticTokenProvider(),
        transport=httpx.ASGITransport(app=fake.app),
    )


def _enforcer() -> CapabilityEnforcer:
    return CapabilityEnforcer(
        {
            "qa-engineer": {Capability.READ},
            "devops": {Capability.READ, Capability.WRITE},
        }
    )


def _gate_plan() -> Plan:
    """A read item (denied at N1) + a HIGH write item (unconfirmed at N2)."""
    plan = Plan(
        session_id="s-gate",
        runbook_id="rb",
        runbook_version="1.0.0",
        title="gate",
        summary="s",
        explanation="e",
        responsible_profile="devops",
        items=[],
    )
    plan.items = [
        PlanItem(
            plan_id=plan.plan_id,
            sequence_num=1,
            runbook_id="rb",
            task_id="read",
            tool="qa-mcp.run_tests",
            capability=Capability.READ,
            risk=RiskLevel.LOW,
            required=False,
            label="Run tests",
            responsible="qa-engineer",
            input_data={"suite": "unit"},
        ),
        PlanItem(
            plan_id=plan.plan_id,
            sequence_num=2,
            runbook_id="rb",
            task_id="deploy",
            tool="deploy-mcp.create_deployment",
            capability=Capability.WRITE,
            risk=RiskLevel.HIGH,
            required=False,
            label="Deploy prod",
            responsible="devops",
            input_data={"service": "api"},
        ),
    ]
    return plan


@pytest.mark.asyncio
async def test_n1_denied_and_n2_unconfirmed_both_skipped_no_abort() -> None:
    fake = FakeGateway()
    repo = InMemoryPlanRepository()
    plan = _gate_plan()
    await repo.create(plan)
    ids = {i.task_id: i.item_id for i in plan.items}

    # Decision: NOTHING approved at N1 (no labels), and the HIGH item is only
    # reachable via N2 confirmation which we do not give.
    decision = ApprovalDecision(
        approved_item_ids={ids["deploy"]},  # HIGH item approved at N1...
        high_risk_confirmed_ids=set(),  # ...but NOT confirmed at N2 (unanswered)
        high_risk_unanswered_ids={ids["deploy"]},
    )
    # 'read' is not in approved_item_ids -> denied at N1.

    executor = PlanExecutor(repo, _client(fake), _enforcer())
    results = {
        r.task_id: r
        async for r in executor.execute(plan, run_id="run-gate", decision=decision)
    }

    assert results["read"].status is ItemStatus.SKIPPED
    assert "N1" in (results["read"].error or "")
    assert results["deploy"].status is ItemStatus.SKIPPED
    assert "unanswered" in (results["deploy"].error or "")

    # The plan did NOT abort mid-loop: it closed with a terminal status and the
    # HIGH tool was never dispatched to the gateway.
    stored = await repo.load(plan.plan_id)
    assert stored.status in {PlanStatus.PARTIAL, PlanStatus.FAILED, PlanStatus.DONE}
    assert fake.idempotency_keys == []  # nothing was executed


@pytest.mark.asyncio
async def test_n2_confirmed_high_risk_executes() -> None:
    """Sanity: with an explicit N2 confirmation the HIGH item DOES run."""
    fake = FakeGateway()
    repo = InMemoryPlanRepository()
    plan = _gate_plan()
    await repo.create(plan)

    # Resolve via the real gate so the confirmation path is exercised end-to-end.
    ids = {i.task_id: i.item_id for i in plan.items}
    decision = ApprovalGate().resolve(
        plan,
        response_value={"__approve_all__": True, "__confirm_high__": [ids["deploy"]]},
    )
    assert ids["deploy"] in decision.high_risk_confirmed_ids

    executor = PlanExecutor(repo, _client(fake), _enforcer())
    results = {
        r.task_id: r
        async for r in executor.execute(plan, run_id="run-gate2", decision=decision)
    }

    # 'read' is a known canned tool -> DONE; 'deploy' is unknown to the fake
    # gateway -> ERROR (NOT skipped: it passed both gates and was dispatched).
    assert results["read"].status is ItemStatus.DONE
    assert results["deploy"].status is ItemStatus.ERROR  # dispatched, tool unknown
    # The high-risk tool WAS dispatched (proves N2 let it through).
    assert any(tool == "deploy-mcp.create_deployment" for tool, _ in fake.idempotency_keys)


def _read_chain_plan() -> Plan:
    """Three independent read items (all known to the fake gateway)."""
    plan = Plan(
        session_id="s-budget",
        runbook_id="rb",
        runbook_version="1.0.0",
        title="budget",
        summary="s",
        explanation="e",
        responsible_profile="qa-engineer",
        items=[],
    )
    plan.items = [
        PlanItem(
            plan_id=plan.plan_id,
            sequence_num=1,
            runbook_id="rb",
            task_id="t1",
            tool="services-mcp.check_health",
            capability=Capability.READ,
            required=False,
            label="health",
            responsible="qa-engineer",
        ),
        PlanItem(
            plan_id=plan.plan_id,
            sequence_num=2,
            runbook_id="rb",
            task_id="t2",
            tool="qa-mcp.run_tests",
            capability=Capability.READ,
            required=False,
            label="tests",
            responsible="qa-engineer",
            input_data={"suite": "unit"},
        ),
        PlanItem(
            plan_id=plan.plan_id,
            sequence_num=3,
            runbook_id="rb",
            task_id="t3",
            tool="qa-mcp.generate_report",
            capability=Capability.READ,
            required=False,
            label="report",
            responsible="qa-engineer",
        ),
    ]
    return plan


@pytest.mark.asyncio
async def test_budget_exceeded_midplan_skips_remaining() -> None:
    fake = FakeGateway()
    repo = InMemoryPlanRepository()
    plan = _read_chain_plan()
    await repo.create(plan)

    # One tool call allowed: item 1 runs, then the budget trips for items 2 & 3.
    budget = RunBudget(max_tokens=10_000, max_wall_clock_s=10_000.0, max_tool_calls=1)
    budget.start()

    executor = PlanExecutor(repo, _client(fake), _enforcer())
    results = {
        r.task_id: r
        async for r in executor.execute(plan, run_id="run-budget", budget=budget)
    }

    assert results["t1"].status is ItemStatus.DONE
    assert results["t2"].status is ItemStatus.SKIPPED
    assert results["t3"].status is ItemStatus.SKIPPED
    assert "budget" in (results["t2"].error or "")
    assert "budget" in (results["t3"].error or "")

    # Exactly one tool actually hit the gateway.
    assert len(fake.idempotency_keys) == 1

    # The plan still reached a terminal status (clean stop, not a hang/abort).
    stored = await repo.load(plan.plan_id)
    assert stored.status in {PlanStatus.PARTIAL, PlanStatus.DONE, PlanStatus.FAILED}
