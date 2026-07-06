"""Unit tests for the ApprovalGate (N1 plan selection + N2 per-item high-risk).

Covers, per critique §1.11 / §2.3:
- N1 selection by label; "approve all" / verbal covers N1;
- N2: verbal / "approve all" NEVER covers a high-risk item;
- N2 requires the explicit ``{"__confirm_high__": [item_id]}`` signal per item;
- an unconfirmed high-risk item is *unanswered*, not rejected.
"""

from __future__ import annotations

import pytest

from app.dev_agent.models.plan import (
    Capability,
    Plan,
    PlanItem,
    RiskLevel,
)
from app.dev_agent.plan.approval import (
    APPROVE_ALL,
    CONFIRM_HIGH,
    ApprovalDecision,
    ApprovalGate,
)


def _plan_with_high() -> Plan:
    """A plan with one LOW read item and one HIGH write item."""
    plan = Plan(
        session_id="s-appr",
        runbook_id="rb",
        runbook_version="1.0.0",
        title="t",
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
            label="Run tests",
            responsible="qa-engineer",
        ),
        PlanItem(
            plan_id=plan.plan_id,
            sequence_num=2,
            runbook_id="rb",
            task_id="deploy",
            tool="deploy-mcp.create_deployment",
            capability=Capability.WRITE,
            risk=RiskLevel.HIGH,
            label="Deploy prod",
            responsible="devops",
        ),
    ]
    return plan


def _ids(plan: Plan) -> dict[str, str]:
    return {i.task_id: i.item_id for i in plan.items}


def test_n1_selection_by_label() -> None:
    plan = _plan_with_high()
    ids = _ids(plan)
    decision = ApprovalGate().resolve(plan, response_value=["Run tests"])

    assert decision.approved_item_ids == {ids["read"]}
    assert decision.rejected is False
    # No high-risk item was selected => nothing unanswered/confirmed.
    assert decision.high_risk_confirmed_ids == set()
    assert decision.high_risk_unanswered_ids == set()


def test_empty_response_approves_nothing() -> None:
    plan = _plan_with_high()
    decision = ApprovalGate().resolve(plan, response_value=None)
    assert decision == ApprovalDecision()
    assert decision.approved_item_ids == set()
    assert decision.rejected is False  # not rejected — caller re-polls


def test_verbal_rejection() -> None:
    plan = _plan_with_high()
    decision = ApprovalGate().resolve(plan, response_value="nao")
    assert decision.rejected is True
    assert decision.approved_item_ids == set()


@pytest.mark.parametrize("verbal", ["sim", "aprovar todos", APPROVE_ALL, "approve all"])
def test_verbal_or_all_covers_n1_but_not_high_risk(verbal: str) -> None:
    """'Approve all' / verbal approves N1 for every item, but the HIGH item is
    only *unanswered* — never confirmed for N2."""
    plan = _plan_with_high()
    ids = _ids(plan)
    decision = ApprovalGate().resolve(plan, response_value=verbal)

    # N1: every item is approved.
    assert decision.approved_item_ids == set(ids.values())
    # N2: the high-risk item is NOT confirmed by verbal/all — it is unanswered.
    assert decision.high_risk_confirmed_ids == set()
    assert decision.high_risk_unanswered_ids == {ids["deploy"]}
    assert decision.rejected is False


def test_n2_requires_confirm_high_per_item() -> None:
    """The HIGH item executes only when explicitly listed in __confirm_high__."""
    plan = _plan_with_high()
    ids = _ids(plan)
    decision = ApprovalGate().resolve(
        plan,
        response_value={
            APPROVE_ALL: True,
            CONFIRM_HIGH: [ids["deploy"]],
        },
    )

    assert decision.approved_item_ids == set(ids.values())
    assert decision.high_risk_confirmed_ids == {ids["deploy"]}
    # Once confirmed, it is no longer unanswered.
    assert decision.high_risk_unanswered_ids == set()


def test_confirm_high_implies_n1_approval() -> None:
    """Confirming a HIGH item (N2) implicitly approves it at N1 even if the label
    was not in the N1 selection."""
    plan = _plan_with_high()
    ids = _ids(plan)
    decision = ApprovalGate().resolve(
        plan,
        response_value={"labels": ["Run tests"], CONFIRM_HIGH: [ids["deploy"]]},
    )

    assert decision.approved_item_ids == {ids["read"], ids["deploy"]}
    assert decision.high_risk_confirmed_ids == {ids["deploy"]}
    assert decision.high_risk_unanswered_ids == set()


def test_unanswered_is_not_rejected() -> None:
    """A HIGH item approved at N1 but not confirmed is unanswered (§1.11): the
    decision is NOT a rejection, so the caller can re-prompt."""
    plan = _plan_with_high()
    ids = _ids(plan)
    decision = ApprovalGate().resolve(
        plan,
        response_value={APPROVE_ALL: True},  # N1 yes, N2 silent
    )

    assert decision.rejected is False
    assert ids["deploy"] in decision.high_risk_unanswered_ids
    assert ids["deploy"] not in decision.high_risk_confirmed_ids


def test_build_high_risk_poll_only_high_items() -> None:
    plan = _plan_with_high()
    ids = _ids(plan)
    poll = ApprovalGate.build_high_risk_poll(plan)

    assert poll["type"] == "poll_multi"
    assert poll["question_id"] == f"{plan.question_id}_highrisk"
    # Only the HIGH item is offered.
    assert poll["options"] == ["Deploy prod [deploy-mcp.create_deployment]"]
    assert poll["metadata"]["item_ids"] == [ids["deploy"]]
    assert poll["metadata"]["confirm_key"] == CONFIRM_HIGH
    assert poll["max_select"] == 1
