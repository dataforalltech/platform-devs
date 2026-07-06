"""Unit tests for PlanExecutor.

Runs the executor against a real GatewayToolClient wired to the in-process fake
gateway via ``httpx.ASGITransport`` (real JSON-RPC over the real httpx stack, no
socket). Covers: full read-only plan -> all DONE / plan DONE; guarded transition
idempotency (expected != current -> no-op); chained skip (dep fails -> dependent
SKIPPED); and capability enforcement (a WRITE item for a profile without WRITE ->
item ERROR, plan does NOT abort).
"""

from __future__ import annotations

import httpx
import pytest

from app.dev_agent.capability import CapabilityEnforcer, CapabilityResolver
from app.dev_agent.gateway.client import GatewayToolClient
from app.dev_agent.models.plan import (
    Capability,
    ItemStatus,
    Plan,
    PlanItem,
    PlanStatus,
    RiskLevel,
)
from app.dev_agent.plan.builder import PlanBuilder
from app.dev_agent.plan.executor import PlanExecutor
from app.dev_agent.plan.repository import InMemoryPlanRepository
from tests._fake_gateway import FakeGateway, StaticTokenProvider


def _client(fake: FakeGateway) -> GatewayToolClient:
    return GatewayToolClient(
        base_url="http://gateway.test/mcp",
        token_provider=StaticTokenProvider(),
        transport=httpx.ASGITransport(app=fake.app),
    )


def _read_plan() -> Plan:
    """The walking-skeleton runbook plan (all reads), with valid inputs."""
    return PlanBuilder(CapabilityResolver()).build_from_runbook(
        runbook_id="health_to_report",
        session_id="s-exec",
        inputs_by_task={
            "check_health": {"service": "api"},
            "run_tests": {"suite": "unit"},
        },
    )


# All personas in the read plan are read-only; that is enough for read tools.
def _read_enforcer() -> CapabilityEnforcer:
    return CapabilityEnforcer(
        {
            "devops": {Capability.READ},
            "qa-engineer": {Capability.READ},
        }
    )


@pytest.mark.asyncio
async def test_executor_runs_full_read_plan_all_done() -> None:
    fake = FakeGateway()
    repo = InMemoryPlanRepository()
    plan = _read_plan()
    await repo.create(plan)

    executor = PlanExecutor(repo, _client(fake), _read_enforcer())
    results = [r async for r in executor.execute(plan, run_id="run-1")]

    assert [r.status for r in results] == [ItemStatus.DONE] * 3
    assert {r.task_id for r in results} == {"check_health", "run_tests", "generate_report"}

    stored = await repo.load(plan.plan_id)
    assert stored.status is PlanStatus.DONE
    assert all(i.status is ItemStatus.DONE for i in stored.items)
    # Output was persisted from the canned gateway result.
    by_task = {i.task_id: i for i in stored.items}
    assert by_task["run_tests"].output_json == {"passed": 42, "failed": 0, "suite": "unit"}

    # The client always sent an Idempotency-Key (one per item, all non-empty).
    assert len(fake.idempotency_keys) == 3
    assert all(key for _, key in fake.idempotency_keys)
    # And it matched each item's own idempotency_key.
    sent = {tool: key for tool, key in fake.idempotency_keys}
    item_keys = {i.tool: i.idempotency_key for i in plan.items}
    assert sent == item_keys


@pytest.mark.asyncio
async def test_guarded_transition_is_idempotent_noop() -> None:
    """A transition whose expected != current status is a no-op returning False."""
    repo = InMemoryPlanRepository()
    plan = _read_plan()
    await repo.create(plan)
    item_id = plan.items[0].item_id

    # Claim PENDING -> EXECUTING succeeds once.
    assert await repo.transition_item(
        item_id, expected=(ItemStatus.PENDING,), new=ItemStatus.EXECUTING
    ) is True
    # A second claim from PENDING no longer matches (already EXECUTING) -> no-op.
    assert await repo.transition_item(
        item_id, expected=(ItemStatus.PENDING,), new=ItemStatus.EXECUTING
    ) is False
    # Plan-level guard likewise: wrong expected -> no-op.
    assert await repo.transition_plan(
        plan.plan_id, expected=(PlanStatus.DONE,), new=PlanStatus.FAILED
    ) is False
    stored = await repo.load(plan.plan_id)
    assert stored.status is PlanStatus.PENDING  # unchanged


@pytest.mark.asyncio
async def test_chained_skip_when_dependency_fails() -> None:
    """A tool the fake gateway does not know -> item ERROR; dependents SKIPPED."""
    fake = FakeGateway()
    repo = InMemoryPlanRepository()

    # Hand-build a 3-item chain a -> b -> c where 'a' calls an unknown tool.
    plan = Plan(
        session_id="s-skip",
        runbook_id="rb",
        runbook_version="1.0.0",
        title="chain",
        summary="s",
        explanation="e",
        responsible_profile="qa-engineer",
        items=[],
    )
    items = [
        PlanItem(
            plan_id=plan.plan_id,
            sequence_num=1,
            runbook_id="rb",
            task_id="a",
            tool="qa-mcp.unknown_tool",  # gateway returns a JSON-RPC error
            capability=Capability.READ,
            required=True,
            label="a",
            responsible="qa-engineer",
        ),
        PlanItem(
            plan_id=plan.plan_id,
            sequence_num=2,
            runbook_id="rb",
            task_id="b",
            depends_on=["a"],
            tool="qa-mcp.run_tests",
            capability=Capability.READ,
            required=True,
            label="b",
            responsible="qa-engineer",
            input_data={"suite": "unit"},
        ),
        PlanItem(
            plan_id=plan.plan_id,
            sequence_num=3,
            runbook_id="rb",
            task_id="c",
            depends_on=["b"],
            tool="qa-mcp.generate_report",
            capability=Capability.READ,
            required=False,
            label="c",
            responsible="qa-engineer",
        ),
    ]
    plan.items = items
    await repo.create(plan)

    executor = PlanExecutor(repo, _client(fake), _read_enforcer())
    results = {r.task_id: r async for r in executor.execute(plan, run_id="run-skip")}

    assert results["a"].status is ItemStatus.ERROR
    assert results["b"].status is ItemStatus.SKIPPED  # dep 'a' not DONE
    assert results["c"].status is ItemStatus.SKIPPED  # dep 'b' not DONE
    # A required item failed => FAILED (does NOT abort mid-loop; all 3 reported).
    stored = await repo.load(plan.plan_id)
    assert stored.status is PlanStatus.FAILED


@pytest.mark.asyncio
async def test_capability_violation_makes_item_error_not_abort() -> None:
    """A WRITE item for a profile without WRITE -> item ERROR; plan not aborted."""
    fake = FakeGateway()
    repo = InMemoryPlanRepository()

    plan = Plan(
        session_id="s-cap",
        runbook_id="rb",
        runbook_version="1.0.0",
        title="cap",
        summary="s",
        explanation="e",
        responsible_profile="qa-engineer",
        items=[],
    )
    plan.items = [
        # A WRITE item owned by a read-only profile -> CapabilityViolation.
        PlanItem(
            plan_id=plan.plan_id,
            sequence_num=1,
            runbook_id="rb",
            task_id="w",
            tool="config-mcp.set_config",
            capability=Capability.WRITE,
            risk=RiskLevel.MEDIUM,
            required=False,  # optional so the plan can still finish PARTIAL
            label="write",
            responsible="qa-engineer",  # granted READ only below
        ),
        # An independent read item that should still run to DONE afterwards.
        PlanItem(
            plan_id=plan.plan_id,
            sequence_num=2,
            runbook_id="rb",
            task_id="r",
            tool="qa-mcp.run_tests",
            capability=Capability.READ,
            required=True,
            label="read",
            responsible="qa-engineer",
            input_data={"suite": "unit"},
        ),
    ]
    await repo.create(plan)

    enforcer = CapabilityEnforcer({"qa-engineer": {Capability.READ}})
    executor = PlanExecutor(repo, _client(fake), enforcer)
    results = {r.task_id: r async for r in executor.execute(plan, run_id="run-cap")}

    assert results["w"].status is ItemStatus.ERROR  # violation -> ERROR, not raise
    assert "capability" in (results["w"].error or "")
    assert results["r"].status is ItemStatus.DONE  # plan did NOT abort

    stored = await repo.load(plan.plan_id)
    # required 'r' is DONE, optional 'w' errored => not FAILED, not all DONE => PARTIAL.
    assert stored.status is PlanStatus.PARTIAL
