"""Read-only PlanExecutor — one path, via the gateway, guarded, enforced.

This is the first "autonomous E2E" of the walking skeleton (critique §3, step 6):
iterate items in topological (``sequence_num``) order, call each tool VIA the
gateway, record DONE, close the plan. No REST, no in-process import, no "Phase C"
stub that marks an item DONE without executing it.

Design points carried straight from the critique:

- **§1.7 — enforcement inside the try.** ``assert_allowed`` runs *inside* the
  per-item ``try``. A :class:`CapabilityViolation` therefore turns the item into
  ERROR; it never escapes the loop and aborts the whole plan.
- **§1.8 — ``required`` drives the final status.** A required item that failed
  => FAILED; otherwise ``done == total`` => DONE, else PARTIAL.
- **§4 / §1.9 — write resume policy.** A WRITE item stuck EXECUTING (orphan) is
  NOT re-executed; ``reconcile_orphans`` moves it to NEEDS_RECONFIRM first, and
  the guarded claim (``expected=(PENDING, READY)``) then no longer matches, so
  the executor skips it (resume-safe) rather than duplicating the side effect.

Approval gating (N1/N2, critique §1.11 / §2.3): pass an
:class:`~app.dev_agent.plan.approval.ApprovalDecision`. When ``decision is None``
every item is treated as approved (the read-only skeleton, no gate). With a
decision, an item runs only if it is in ``approved_item_ids`` (N1) and — for a
HIGH-risk item — only if it is in ``high_risk_confirmed_ids`` (N2); a HIGH item
that was approved but never confirmed is SKIPPED as *unanswered* (distinct from
"not approved"). Verbal/"approve all" never cover high-risk.

Cost control (critique §2.1): pass a :class:`~app.dev_agent.budget.RunBudget`.
Before each tool dispatch the executor charges a tool call and checks the
budget; a :class:`~app.dev_agent.budget.BudgetExceeded` stops the run cleanly —
the remaining items are SKIPPED ("budget exceeded") and the plan is still closed
with a coherent final status. ``budget is None`` means no ceiling.

Redaction (critique §2.7): the output of a sensitive tool
(:data:`~app.dev_agent.security.redaction.SENSITIVE_TOOLS`) is redacted before it
is persisted or placed on an :class:`ItemResult`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from app.dev_agent.budget import BudgetExceeded
from app.dev_agent.capability import CapabilityEnforcer
from app.dev_agent.catalog import PolicyEngine, RegistryCapabilityResolver
from app.dev_agent.gateway.client import GatewayToolClient, build_correlation
from app.dev_agent.models.plan import (
    ItemResult,
    ItemStatus,
    Plan,
    PlanItem,
    PlanStatus,
    RiskLevel,
)
from app.dev_agent.plan.approval import ApprovalDecision
from app.dev_agent.plan.repository import PlanRepository
from app.dev_agent.security import redact

if TYPE_CHECKING:  # avoid a hard import cycle / keep budget optional at call sites
    from app.dev_agent.budget import RunBudget

# Items in a terminal state are never re-run on resume.
_TERMINAL_ITEM_STATES: frozenset[ItemStatus] = frozenset(
    {ItemStatus.DONE, ItemStatus.ERROR, ItemStatus.SKIPPED}
)
# States from which an item may be claimed for execution (guarded).
_CLAIMABLE_ITEM_STATES: tuple[ItemStatus, ...] = (
    ItemStatus.PENDING,
    ItemStatus.READY,
    ItemStatus.APPROVED,
)


class PlanExecutor:
    """Execute a plan's items sequentially through the gateway (read-only slice)."""

    def __init__(
        self,
        repo: PlanRepository,
        gateway: GatewayToolClient,
        enforcer: CapabilityEnforcer,
        *,
        resolver: RegistryCapabilityResolver | None = None,
        policy: PolicyEngine | None = None,
    ) -> None:
        self._repo = repo
        self._gateway = gateway
        self._enforcer = enforcer
        # Fase 2: PDP por recurso/efeito, opcional. Sem os dois, comportamento
        # inalterado (só o gate read/write do enforcer). Com eles, cada item é
        # avaliado contra o catálogo (source of truth) antes de rodar.
        self._resolver = resolver
        self._policy = policy

    async def execute(
        self,
        plan: Plan,
        *,
        run_id: str,
        decision: ApprovalDecision | None = None,
        budget: "RunBudget | None" = None,
        tenant_id: str | None = None,
    ) -> AsyncIterator[ItemResult]:
        """Run ``plan`` and yield an :class:`ItemResult` per non-terminal item.

        ``decision=None`` means "all approved" (the read-only skeleton, no gate).
        With a decision, N1 (``approved_item_ids``) and N2 (``high_risk_confirmed_ids``
        for HIGH items) gate each item. ``budget=None`` means no ceiling; a
        :class:`~app.dev_agent.budget.RunBudget` stops the run cleanly on
        :class:`~app.dev_agent.budget.BudgetExceeded` (remaining items SKIPPED).
        The plan is claimed with a guarded ``PENDING/APPROVED -> EXECUTING`` and,
        on close, transitioned to its final status derived from ``required``.
        ``tenant_id`` (when set) becomes the ``X-Tenant-Id`` header the REAL
        gateway requires (SEC-035); ``None`` for the local fake-gateway E2E.
        """
        # Guarded plan claim; if another worker already moved it, resume from the
        # currently persisted state (some items may already be DONE).
        await self._repo.transition_plan(
            plan.plan_id,
            expected=(PlanStatus.PENDING, PlanStatus.APPROVED),
            new=PlanStatus.EXECUTING,
        )
        plan = await self._repo.load(plan.plan_id)

        order = sorted(plan.items, key=lambda i: i.sequence_num)
        done_task_ids: set[str] = {
            i.task_id for i in plan.items if i.status is ItemStatus.DONE
        }
        results: list[ItemResult] = []
        budget_exhausted = False

        for item in order:
            # RESUME: never re-run an item already in a terminal state.
            if item.status in _TERMINAL_ITEM_STATES:
                continue

            # Once the budget is spent, every remaining non-terminal item is
            # SKIPPED (clean stop, coherent final status).
            if budget_exhausted:
                result = await self._skip(item, "budget exceeded")
                results.append(result)
                yield result
                continue

            # Chained skip: a dependency that did not complete DONE poisons the
            # dependent (it would run with the dependency's empty/absent output).
            if any(dep not in done_task_ids for dep in item.depends_on):
                result = await self._skip(item, "dependency did not complete")
                results.append(result)
                yield result
                continue

            # Approval gate N1. decision=None => all approved.
            if decision is not None and item.item_id not in decision.approved_item_ids:
                result = await self._skip(item, "not approved (N1)")
                results.append(result)
                yield result
                continue

            # Approval gate N2 — a HIGH-risk item needs INDIVIDUAL confirmation;
            # verbal/"approve all" never covers it. Distinguish "unanswered"
            # (approved at N1 but not confirmed) from a plain N1 rejection.
            if (
                decision is not None
                and item.risk is RiskLevel.HIGH
                and item.item_id not in decision.high_risk_confirmed_ids
            ):
                reason = (
                    "high-risk unanswered (N2)"
                    if item.item_id in decision.high_risk_unanswered_ids
                    else "high-risk not approved (N2)"
                )
                result = await self._skip(item, reason)
                results.append(result)
                yield result
                continue

            # PDP por recurso/efeito (Fase 2 — ADR-005/ADR-009 D9.5). Consulta o
            # catálogo (source of truth): se o (profile, effects/blast/domínio) for
            # negado, o item é SKIPPED como policy_denied (não é erro; não aborta o
            # plano). Só enforça tools CATALOGADAS — tool sem record passa (migração
            # aditiva, D9.10). Antes do budget: item negado não consome orçamento.
            if self._policy is not None and self._resolver is not None:
                record = self._resolver.record(item.tool)
                if record is not None:
                    pdp = self._policy.decide(profile=item.responsible, record=record)
                    if not pdp.allowed:
                        result = await self._skip(item, f"policy_denied (PDP): {pdp.reason}")
                        results.append(result)
                        yield result
                        continue

            # Budget: charge + check BEFORE dispatch, so a spent budget stops the
            # run rather than paying for one more call. On BudgetExceeded, skip
            # THIS item and every remaining one (never escapes the generator, so
            # the final-status flush below still runs).
            if budget is not None:
                budget.charge_tool_call()
                try:
                    budget.check()
                except BudgetExceeded:
                    budget_exhausted = True
                    result = await self._skip(item, "budget exceeded")
                    results.append(result)
                    yield result
                    continue

            # Guarded claim PENDING/READY/APPROVED -> EXECUTING. If the guard
            # does not match (another worker claimed it, or a WRITE orphan was
            # reconciled to NEEDS_RECONFIRM), skip: resume-safe, no double-run.
            claimed = await self._repo.transition_item(
                item.item_id,
                expected=_CLAIMABLE_ITEM_STATES,
                new=ItemStatus.EXECUTING,
            )
            if not claimed:
                continue

            result = await self._run_item(
                item, plan=plan, run_id=run_id, tenant_id=tenant_id
            )
            if result.status is ItemStatus.DONE:
                done_task_ids.add(item.task_id)
            results.append(result)
            yield result

        # Close the plan with a status that respects `required` (critique §1.8).
        final = self._final_status(plan, results, done_task_ids)
        await self._repo.transition_plan(
            plan.plan_id, expected=(PlanStatus.EXECUTING,), new=final
        )

    async def _skip(self, item: PlanItem, reason: str) -> ItemResult:
        """Guarded SKIP of a claimable item, returning the matching ItemResult."""
        await self._repo.transition_item(
            item.item_id,
            expected=_CLAIMABLE_ITEM_STATES,
            new=ItemStatus.SKIPPED,
            error=reason,
        )
        return ItemResult(
            item_id=item.item_id,
            task_id=item.task_id,
            tool=item.tool,
            status=ItemStatus.SKIPPED,
            error=reason,
        )

    async def _run_item(
        self, item: PlanItem, *, plan: Plan, run_id: str, tenant_id: str | None = None
    ) -> ItemResult:
        """Execute one claimed item. Any failure -> ERROR (never escapes)."""
        try:
            # §1.7: enforcement INSIDE the try — a CapabilityViolation becomes an
            # item ERROR, it does not abort the plan.
            self._enforcer.assert_allowed(
                profile=item.responsible,
                capability=item.capability,
                tool=item.tool,
            )
            raw_output = await self._gateway.call_tool(
                item.tool,
                item.input_data,
                idempotency_key=item.idempotency_key,
                capability=item.capability,
                correlation=build_correlation(
                    run_id=run_id,
                    session_id=plan.session_id,
                    agent_profile=item.responsible,
                    tenant_id=tenant_id,
                ),
            )
            # §2.7: redact a sensitive tool's payload BEFORE persist / ItemResult
            # (so a secret never reaches the DB nor the LLM context).
            output = redact(item.tool, raw_output)
            await self._repo.transition_item(
                item.item_id,
                expected=(ItemStatus.EXECUTING,),
                new=ItemStatus.DONE,
                output=output,
            )
            return ItemResult(
                item_id=item.item_id,
                task_id=item.task_id,
                tool=item.tool,
                status=ItemStatus.DONE,
                output=output,
            )
        except Exception as exc:  # noqa: BLE001 - per-item isolation is intentional
            message = str(exc)[:2000]
            await self._repo.transition_item(
                item.item_id,
                expected=(ItemStatus.EXECUTING,),
                new=ItemStatus.ERROR,
                error=message,
            )
            return ItemResult(
                item_id=item.item_id,
                task_id=item.task_id,
                tool=item.tool,
                status=ItemStatus.ERROR,
                error=message,
            )

    @staticmethod
    def _final_status(
        plan: Plan, results: list[ItemResult], done_task_ids: set[str]
    ) -> PlanStatus:
        """Derive the plan's final status using each item's ``required`` flag.

        - a REQUIRED item that ended non-DONE (ERROR or SKIPPED) => FAILED;
        - else all items DONE => DONE;
        - else PARTIAL.
        """
        result_status = {r.item_id: r.status for r in results}
        total = len(plan.items)
        done = 0
        for item in plan.items:
            status = result_status.get(item.item_id, item.status)
            if status is ItemStatus.DONE or item.task_id in done_task_ids:
                done += 1
                continue
            # Non-DONE required item is a blocking failure.
            if item.required:
                return PlanStatus.FAILED
        if done == total:
            return PlanStatus.DONE
        return PlanStatus.PARTIAL
