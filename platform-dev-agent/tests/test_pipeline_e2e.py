"""Full Modo B E2E — plan -> approve -> execute — over the real httpx transport.

This is the capstone of the walking skeleton: the AutonomousPipeline composes
every slice (RunbookSelector, PlanBuilder, PlanRepository, ApprovalGate N1/N2,
PlanExecutor, RunBudget, redaction) into one autonomous loop and runs it against
the in-process fake gateway (real JSON-RPC over httpx ASGITransport).

Covers: approve-all happy path, whole-plan rejection, partial approval (PARTIAL),
budget-bounded run (optional tail skipped -> PARTIAL), empty response (re-prompt),
and no-runbook routing.
"""

from __future__ import annotations

import httpx
import pytest

from app.dev_agent.budget import RunBudget
from app.dev_agent.capability import Capability, CapabilityEnforcer
from app.dev_agent.gateway.client import GatewayToolClient
from app.dev_agent.models.plan import ItemStatus, PlanStatus
from app.dev_agent.pipeline import AutonomousPipeline, NoRunbookError
from app.dev_agent.plan.repository import InMemoryPlanRepository
from app.dev_agent.runbook_selector import RunbookSelector
from tests._fake_gateway import FakeGateway, StaticTokenProvider

# Labels come from the runbook task titles (catalog.py).
_HEALTH = "Check service health"
_TESTS = "Run test suite"
_REPORT = "Generate QA report"

_INPUTS = {"check_health": {"service": "api"}, "run_tests": {"suite": "unit"}}


def _make_pipeline() -> tuple[AutonomousPipeline, FakeGateway, InMemoryPlanRepository]:
    fake = FakeGateway()
    repo = InMemoryPlanRepository()
    client = GatewayToolClient(
        base_url="http://gateway.local/mcp",
        token_provider=StaticTokenProvider(),
        transport=httpx.ASGITransport(app=fake.app),
    )
    enforcer = CapabilityEnforcer(
        {"devops": {Capability.READ}, "qa-engineer": {Capability.READ}}
    )
    pipeline = AutonomousPipeline(
        repo=repo, gateway=client, enforcer=enforcer, selector=RunbookSelector()
    )
    return pipeline, fake, repo


async def _propose(pipeline: AutonomousPipeline):
    return await pipeline.plan(
        message="check the service and run the tests",
        session_id="s1",
        entity_type="service_health",  # routes deterministically -> health_to_report
        inputs_by_task=_INPUTS,
    )


@pytest.mark.asyncio
async def test_plan_persists_pending_and_returns_poll() -> None:
    pipeline, _fake, repo = _make_pipeline()
    proposal = await _propose(pipeline)

    assert proposal.plan.runbook_id == "health_to_report"
    assert proposal.plan.runbook_version == "1.0.0"
    assert proposal.high_risk_poll is None  # read-only runbook, no HIGH steps
    assert proposal.approval_poll["question_id"] == proposal.plan.question_id
    assert len(proposal.approval_poll["options"]) == 3

    stored = await repo.load(proposal.plan.plan_id)
    assert stored.status is PlanStatus.PENDING  # awaiting approval, nothing ran


@pytest.mark.asyncio
async def test_approve_all_executes_whole_plan() -> None:
    pipeline, fake, repo = _make_pipeline()
    proposal = await _propose(pipeline)

    outcome = await pipeline.execute(
        question_id=proposal.plan.question_id,
        response_value="__approve_all__",
        run_id="run-1",
    )

    assert outcome.status is PlanStatus.DONE
    assert [r.status for r in outcome.results] == [ItemStatus.DONE] * 3
    # The three tools really traversed the gateway, in DAG order.
    assert [tool for tool, _ in fake.idempotency_keys] == [
        "services-mcp.check_health",
        "qa-mcp.run_unit_tests",
        "qa-mcp.generate_qa_report",
    ]
    stored = await repo.load(proposal.plan.plan_id)
    assert stored.status is PlanStatus.DONE


@pytest.mark.asyncio
async def test_whole_plan_rejection() -> None:
    pipeline, fake, repo = _make_pipeline()
    proposal = await _propose(pipeline)

    outcome = await pipeline.execute(
        question_id=proposal.plan.question_id,
        response_value="nao",
        run_id="run-2",
    )

    assert outcome.status is PlanStatus.REJECTED
    assert outcome.results == []
    assert fake.idempotency_keys == []  # nothing dispatched
    stored = await repo.load(proposal.plan.plan_id)
    assert stored.status is PlanStatus.REJECTED


@pytest.mark.asyncio
async def test_partial_approval_of_required_steps() -> None:
    pipeline, _fake, repo = _make_pipeline()
    proposal = await _propose(pipeline)

    # Approve the two required steps but not the optional report.
    outcome = await pipeline.execute(
        question_id=proposal.plan.question_id,
        response_value=[_HEALTH, _TESTS],
        run_id="run-3",
    )

    by_task = {r.task_id: r.status for r in outcome.results}
    assert by_task["check_health"] is ItemStatus.DONE
    assert by_task["run_tests"] is ItemStatus.DONE
    assert by_task["generate_report"] is ItemStatus.SKIPPED  # not approved (N1)
    assert outcome.status is PlanStatus.PARTIAL  # only the optional tail skipped


@pytest.mark.asyncio
async def test_budget_stops_optional_tail() -> None:
    pipeline, fake, repo = _make_pipeline()
    proposal = await _propose(pipeline)

    # Two tool calls allowed: the two required steps run; the optional report
    # trips the budget and is skipped -> PARTIAL (no required step failed).
    budget = RunBudget(max_tokens=10**9, max_wall_clock_s=10**9, max_tool_calls=2)
    outcome = await pipeline.execute(
        question_id=proposal.plan.question_id,
        response_value="__approve_all__",
        run_id="run-4",
        budget=budget,
    )

    by_task = {r.task_id: r.status for r in outcome.results}
    assert by_task["check_health"] is ItemStatus.DONE
    assert by_task["run_tests"] is ItemStatus.DONE
    assert by_task["generate_report"] is ItemStatus.SKIPPED
    assert outcome.status is PlanStatus.PARTIAL
    assert len(fake.idempotency_keys) == 2  # only two tools actually dispatched


@pytest.mark.asyncio
async def test_empty_response_requests_reprompt() -> None:
    pipeline, fake, repo = _make_pipeline()
    proposal = await _propose(pipeline)

    outcome = await pipeline.execute(
        question_id=proposal.plan.question_id,
        response_value=None,
        run_id="run-5",
    )

    assert outcome.needs_reprompt is True
    assert outcome.results == []
    assert fake.idempotency_keys == []
    stored = await repo.load(proposal.plan.plan_id)
    assert stored.status is PlanStatus.PENDING  # untouched, awaiting a real answer


@pytest.mark.asyncio
async def test_no_runbook_match_raises() -> None:
    pipeline, _fake, _repo = _make_pipeline()
    with pytest.raises(NoRunbookError):
        await pipeline.plan(
            message="do something unmapped",
            session_id="s2",
            entity_type="totally_unknown_domain",
        )
