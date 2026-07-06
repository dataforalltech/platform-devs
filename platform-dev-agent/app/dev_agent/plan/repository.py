"""Plan persistence with GUARDED transitions (the basis of idempotency).

Every status change of a plan or item is *guarded*: the write only happens when
the current status is in an explicit ``expected`` set. That single rule is what
eliminates the marketing agent's TOCTOU double-execution gotcha (critique §6):
two workers racing the same item can only have one win the ``PENDING -> EXECUTING``
claim, and a resume never re-runs an item that already reached a terminal state.

Only the interface (:class:`PlanRepository`) and an in-memory implementation are
provided here. The Postgres implementation (guarded ``UPDATE ... WHERE status =
ANY(...)`` against ``dev_plans`` / ``dev_plan_items`` / ``dev_plan_approvals``,
per spec §6) is a later slice; the ABC pins the contract it must honour.

Orphan reconciliation (critique §2.5): an item left in EXECUTING by a crash never
again matches ``expected=(PENDING, READY)`` and would be stuck forever. Before a
resume re-claims, :meth:`reconcile_orphans` moves items stuck in EXECUTING beyond
a TTL to NEEDS_RECONFIRM for WRITE items (a write must NOT be re-executed blindly,
spec §4/§1.9) or re-claims READ items (safe to retry).
"""

from __future__ import annotations

import abc
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from app.dev_agent.models.plan import (
    Capability,
    ItemStatus,
    Plan,
    PlanStatus,
)


class PlanRepository(abc.ABC):
    """Abstract plan store. All status mutations are guarded (see module docstring)."""

    @abc.abstractmethod
    async def create(self, plan: Plan) -> None:
        """Persist ``plan`` and its items (initial status as carried by the model)."""

    @abc.abstractmethod
    async def load(self, plan_id: str) -> Plan:
        """Return the current persisted state of the plan. Raises ``KeyError`` if absent."""

    @abc.abstractmethod
    async def get_by_question_id(self, question_id: str) -> Plan | None:
        """Correlate a poll response to its plan (UNIQUE ``question_id``); ``None`` if absent."""

    @abc.abstractmethod
    async def transition_plan(
        self,
        plan_id: str,
        *,
        expected: Sequence[PlanStatus],
        new: PlanStatus,
    ) -> bool:
        """Guarded plan transition. Change status only if current ∈ ``expected``.

        Returns ``True`` iff the status was changed (i.e. the guard matched).
        """

    @abc.abstractmethod
    async def transition_item(
        self,
        item_id: str,
        *,
        expected: Sequence[ItemStatus],
        new: ItemStatus,
        output: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> bool:
        """Guarded item transition. Change status only if current ∈ ``expected``.

        On success optionally records ``output`` and/or ``error``. Returns
        ``True`` iff the status was changed (the guard is the idempotency point).
        """

    @abc.abstractmethod
    async def record_approval(
        self,
        *,
        plan_id: str,
        approved_by: str,
        approved_item_ids: list[str],
        high_risk_confirmed_ids: list[str],
        run_id: str | None,
        response_value: Any,
    ) -> None:
        """Append ONE audit row per approval, persisting the actual item ids."""

    @abc.abstractmethod
    async def reconcile_orphans(
        self,
        plan_id: str,
        *,
        executing_ttl_s: float,
    ) -> list[str]:
        """Reconcile items stuck in EXECUTING beyond ``executing_ttl_s``.

        WRITE items -> NEEDS_RECONFIRM (never re-executed blindly, spec §4/§1.9);
        READ items are re-claimable -> back to READY (safe to retry). Returns the
        list of item ids that were reconciled.
        """


@dataclass
class _StoredApproval:
    approval_id: str
    plan_id: str
    approved_by: str
    approved_item_ids: list[str]
    high_risk_confirmed_ids: list[str]
    run_id: str | None
    response_value: Any


@dataclass
class _StoredItem:
    """Item state tracked separately from the model so guards operate on storage."""

    status: ItemStatus
    capability: Capability
    output: dict[str, Any] | None = None
    error: str | None = None
    # Wall-clock of the last transition INTO EXECUTING; drives orphan TTL.
    executing_since: float | None = None


class InMemoryPlanRepository(PlanRepository):
    """In-memory guarded plan store (Postgres is a later slice).

    Not thread-safe by lock, but the guarded transitions are the concurrency
    contract: a repeated/racing transition whose guard no longer matches is a
    no-op returning ``False`` — exactly the idempotency behaviour the Postgres
    ``UPDATE ... WHERE status = ANY(...)`` will provide.
    """

    def __init__(self) -> None:
        self._plans: dict[str, Plan] = {}
        self._items: dict[str, _StoredItem] = {}
        # plan_id -> ordered item_ids (preserves sequence for load()).
        self._plan_items: dict[str, list[str]] = {}
        self._by_question: dict[str, str] = {}
        self._approvals: list[_StoredApproval] = []

    async def create(self, plan: Plan) -> None:
        # Deep-copy through pydantic so the store owns an independent snapshot;
        # the caller's Plan object is not mutated by transitions.
        stored = plan.model_copy(deep=True)
        self._plans[stored.plan_id] = stored
        self._plan_items[stored.plan_id] = []
        self._by_question[stored.question_id] = stored.plan_id
        for item in stored.items:
            self._items[item.item_id] = _StoredItem(
                status=item.status,
                capability=item.capability,
                output=item.output_json,
                error=item.error_text,
            )
            self._plan_items[stored.plan_id].append(item.item_id)

    async def load(self, plan_id: str) -> Plan:
        plan = self._plans.get(plan_id)
        if plan is None:
            raise KeyError(f"plan {plan_id!r} not found")
        # Rebuild a fresh Plan reflecting the current stored item/plan status.
        snapshot = plan.model_copy(deep=True)
        for item in snapshot.items:
            si = self._items[item.item_id]
            item.status = si.status
            item.output_json = si.output
            item.error_text = si.error
        return snapshot

    async def get_by_question_id(self, question_id: str) -> Plan | None:
        plan_id = self._by_question.get(question_id)
        if plan_id is None:
            return None
        return await self.load(plan_id)

    async def transition_plan(
        self,
        plan_id: str,
        *,
        expected: Sequence[PlanStatus],
        new: PlanStatus,
    ) -> bool:
        plan = self._plans.get(plan_id)
        if plan is None:
            return False
        if plan.status not in set(expected):
            return False  # guard did not match -> no-op (idempotent)
        plan.status = new
        return True

    async def transition_item(
        self,
        item_id: str,
        *,
        expected: Sequence[ItemStatus],
        new: ItemStatus,
        output: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> bool:
        si = self._items.get(item_id)
        if si is None:
            return False
        if si.status not in set(expected):
            return False  # guard did not match -> no-op (idempotent)
        si.status = new
        if output is not None:
            si.output = output
        if error is not None:
            si.error = error
        si.executing_since = time.monotonic() if new is ItemStatus.EXECUTING else None
        return True

    async def record_approval(
        self,
        *,
        plan_id: str,
        approved_by: str,
        approved_item_ids: list[str],
        high_risk_confirmed_ids: list[str],
        run_id: str | None,
        response_value: Any,
    ) -> None:
        self._approvals.append(
            _StoredApproval(
                approval_id=str(uuid.uuid4()),
                plan_id=plan_id,
                approved_by=approved_by,
                approved_item_ids=list(approved_item_ids),
                high_risk_confirmed_ids=list(high_risk_confirmed_ids),
                run_id=run_id,
                response_value=response_value,
            )
        )

    async def reconcile_orphans(
        self,
        plan_id: str,
        *,
        executing_ttl_s: float,
    ) -> list[str]:
        reconciled: list[str] = []
        now = time.monotonic()
        for item_id in self._plan_items.get(plan_id, []):
            si = self._items[item_id]
            if si.status is not ItemStatus.EXECUTING:
                continue
            since = si.executing_since
            if since is None or (now - since) < executing_ttl_s:
                continue
            if si.capability is Capability.WRITE:
                # A write must NOT be re-executed blindly (spec §4 / §1.9).
                si.status = ItemStatus.NEEDS_RECONFIRM
            else:
                # A read is safe to retry -> re-claimable.
                si.status = ItemStatus.READY
            si.executing_since = None
            reconciled.append(item_id)
        return reconciled

    # --- test/introspection helper (not part of the ABC) ---
    def approvals_for(self, plan_id: str) -> list[_StoredApproval]:
        return [a for a in self._approvals if a.plan_id == plan_id]
