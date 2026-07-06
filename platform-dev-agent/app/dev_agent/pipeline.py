"""Autonomous Modo B pipeline: **plan -> approve -> execute**.

Composes the pieces built across the walking-skeleton slices into the headline
capability — a runbook-derived, human-approved, gateway-executed multi-step plan:

    plan(...)     RunbookSelector -> PlanBuilder -> repo.create(PENDING)
                  -> PlanProposal(plan, approval_poll[, high_risk_poll])   [awaits human]

    execute(...)  repo.get_by_question_id -> ApprovalGate.resolve
                  -> (rejected? -> REJECTED) | (nothing approved? -> re-poll)
                  -> PlanExecutor.execute(decision, budget) -> [ItemResult]

The `analyze` path (persona ReAct chat) is deliberately NOT here: it needs a
GatewayToolProvider (guarded tool wrapping) plus a live LLM and is the next slice.
This pipeline needs none of that — every dependency it uses is already built and
unit-tested, so it is fully exercisable against the in-process fake gateway.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.dev_agent.budget import RunBudget
from app.dev_agent.capability import CapabilityEnforcer, CapabilityResolver
from app.dev_agent.catalog import PolicyEngine, RegistryCapabilityResolver
from app.dev_agent.gateway.client import GatewayToolClient
from app.dev_agent.models.plan import ItemResult, Plan, PlanStatus, RiskLevel
from app.dev_agent.plan.approval import ApprovalGate
from app.dev_agent.plan.builder import PlanBuilder
from app.dev_agent.plan.executor import PlanExecutor
from app.dev_agent.plan.repository import PlanRepository
from app.dev_agent.runbook_selector import RunbookSelector


class NoRunbookError(ValueError):
    """No runbook matched the routing tokens (the selector returned ``None``)."""


@dataclass
class PlanProposal:
    """The output of :meth:`AutonomousPipeline.plan` — awaiting human approval.

    ``approval_poll`` is the N1 poll (all steps). ``high_risk_poll`` is the
    dedicated N2 poll (HIGH steps only) and is ``None`` when the plan has none.
    """

    plan: Plan
    approval_poll: dict[str, Any]
    high_risk_poll: dict[str, Any] | None = None


@dataclass
class ExecutionOutcome:
    """The result of :meth:`AutonomousPipeline.execute`."""

    status: PlanStatus
    results: list[ItemResult]
    # True when nothing was approved and the caller should re-issue the poll
    # (distinct from a rejection, which sets status == REJECTED with no results).
    needs_reprompt: bool = False


class AutonomousPipeline:
    """Compose selector + builder + repository + approval gate + executor."""

    def __init__(
        self,
        *,
        repo: PlanRepository,
        gateway: GatewayToolClient,
        enforcer: CapabilityEnforcer,
        selector: RunbookSelector,
        builder: PlanBuilder | None = None,
        gate: ApprovalGate | None = None,
        resolver: RegistryCapabilityResolver | None = None,
        policy: PolicyEngine | None = None,
    ) -> None:
        self._repo = repo
        self._gateway = gateway
        self._enforcer = enforcer
        self._selector = selector
        # Fase 2: com um RegistryCapabilityResolver, o builder classifica pelo
        # CATÁLOGO (source of truth) e o executor enforça o PDP por efeito/blast.
        # Sem ele, comportamento inalterado (heurística de verbo + só read/write).
        self._resolver = resolver
        self._policy = policy
        self._builder = builder or PlanBuilder(resolver or CapabilityResolver())
        self._gate = gate or ApprovalGate()

    async def plan(
        self,
        *,
        message: str,
        session_id: str,
        intent: str = "",
        entity_type: str | None = None,
        sub_intent: str = "",
        inputs_by_task: dict[str, dict] | None = None,
    ) -> PlanProposal:
        """Select a runbook, build the plan, persist it PENDING, return the poll."""
        runbook_id = self._selector.select(
            intent=intent or message, entity_type=entity_type, sub_intent=sub_intent
        )
        if runbook_id is None:
            raise NoRunbookError(
                f"no runbook matched (entity_type={entity_type!r}, sub_intent={sub_intent!r}); "
                "the caller should fall back to analyze mode or ask the human"
            )
        plan = self._builder.build_from_runbook(
            runbook_id=runbook_id,
            session_id=session_id,
            inputs_by_task=inputs_by_task,
        )
        await self._repo.create(plan)
        high_risk_poll = (
            self._gate.build_high_risk_poll(plan)
            if plan.requires_high_risk_approval()
            else None
        )
        return PlanProposal(
            plan=plan,
            approval_poll=self._build_plan_poll(plan),
            high_risk_poll=high_risk_poll,
        )

    async def execute(
        self,
        *,
        question_id: str,
        response_value: Any,
        run_id: str,
        budget: RunBudget | None = None,
        tenant_id: str | None = None,
    ) -> ExecutionOutcome:
        """Resolve approval for the pending plan and execute the approved items."""
        plan = await self._repo.get_by_question_id(question_id)
        if plan is None:
            raise KeyError(f"no plan for question_id {question_id!r}")

        decision = self._gate.resolve(plan, response_value=response_value)

        if decision.rejected:
            await self._repo.transition_plan(
                plan.plan_id,
                expected=(PlanStatus.PENDING, PlanStatus.APPROVED),
                new=PlanStatus.REJECTED,
            )
            return ExecutionOutcome(status=PlanStatus.REJECTED, results=[])

        # Nothing approved and not a rejection => the caller must re-issue the
        # poll. Leave the plan PENDING; do NOT run the executor (which would
        # skip every item and wrongly close the plan).
        if not decision.approved_item_ids and not decision.high_risk_confirmed_ids:
            return ExecutionOutcome(
                status=PlanStatus.PENDING, results=[], needs_reprompt=True
            )

        if budget is not None:
            budget.start()  # anchor the wall-clock ceiling at the top of the run

        executor = PlanExecutor(
            self._repo, self._gateway, self._enforcer,
            resolver=self._resolver, policy=self._policy,
        )
        results = [
            r
            async for r in executor.execute(
                plan,
                run_id=run_id,
                decision=decision,
                budget=budget,
                tenant_id=tenant_id,
            )
        ]
        final = await self._repo.load(plan.plan_id)
        return ExecutionOutcome(status=final.status, results=results)

    @staticmethod
    def _build_plan_poll(plan: Plan) -> dict[str, Any]:
        """Build the N1 ``poll_multi`` block (all steps), correlated by question_id."""
        return {
            "type": "poll_multi",
            "question": (
                f"Aprovar o plano '{plan.title}' ({len(plan.items)} passos)?"
            ),
            "question_id": plan.question_id,
            "options": [f"{i.label} [{i.tool}]" for i in plan.items],
            "min_select": 0,
            "max_select": len(plan.items),
            "metadata": {
                "plan_id": plan.plan_id,
                "runbook_id": plan.runbook_id,
                "runbook_version": plan.runbook_version,
                "has_high_risk": any(i.risk is RiskLevel.HIGH for i in plan.items),
            },
        }


__all__ = ["AutonomousPipeline", "PlanProposal", "ExecutionOutcome", "NoRunbookError"]
