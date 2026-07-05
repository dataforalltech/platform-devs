"""Postgres implementation of :class:`PlanRepository` (spec §6).

This is the runtime store behind the in-memory contract defined in
``repository.py``. It honours the SAME ABC and the SAME guarded-transition
semantics — the contract suite in ``tests/test_repository_contract.py`` runs
identically against both to prove parity.

Design points (all locked by the ABC / spec §6):

- Every status mutation is a GUARDED ``UPDATE ... WHERE status = ANY($n::text[])``
  ``RETURNING`` — the affected-row count is the idempotency point. A racing or
  repeated transition whose guard no longer matches is a no-op returning ``False``.
- JSONB columns (``depends_on``, ``input_json``, ``output_json``,
  ``approved_item_ids``, ``high_risk_confirmed``, ``response_value``) are written
  with ``json.dumps`` and read back with ``json.loads`` (asyncpg returns JSONB as
  ``str`` unless a codec is registered; we do not assume one is).
- The model field ``PlanItem.input_data`` maps to the DB column ``input_json``.
- ``reconcile_orphans`` uses ``updated_at`` as the "EXECUTING since" clock: an
  item whose last transition (into EXECUTING) is older than ``executing_ttl_s``
  is reconciled — WRITE -> NEEDS_RECONFIRM (never re-run blindly, spec §4/§1.9),
  READ -> READY (safe to retry). Capability is derived from the ``capability``
  column, one guarded UPDATE per capability class.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from typing import Any

import asyncpg  # noqa: F401  (imported so the dependency is explicit; Pool is typed loosely)

from app.dev_agent.models.plan import (
    Capability,
    ItemStatus,
    Plan,
    PlanItem,
    PlanStatus,
    RiskLevel,
)
from app.dev_agent.plan.repository import PlanRepository


def _jsonb_loads(value: Any) -> Any:
    """Decode a JSONB column that asyncpg may hand back as ``str`` or already-decoded."""
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    return json.loads(value)


class PostgresPlanRepository(PlanRepository):
    """asyncpg-backed guarded plan store (spec §6). Same contract as InMemory."""

    def __init__(self, pool: "asyncpg.Pool") -> None:
        self._pool = pool

    # ------------------------------------------------------------------ create
    async def create(self, plan: Plan) -> None:
        """Insert the plan and all its items in a SINGLE transaction."""
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """
                    INSERT INTO dev_plans (
                        plan_id, session_id, run_id, question_id,
                        runbook_id, runbook_version, status,
                        title, summary, responsible_profile
                    ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
                    """,
                    plan.plan_id,
                    plan.session_id,
                    plan.run_id,
                    plan.question_id,
                    plan.runbook_id,
                    plan.runbook_version,
                    plan.status.value,
                    plan.title,
                    plan.summary,
                    plan.responsible_profile,
                )
                for item in plan.items:
                    await conn.execute(
                        """
                        INSERT INTO dev_plan_items (
                            item_id, plan_id, sequence_num,
                            runbook_id, task_id, depends_on,
                            tool, capability, risk, required,
                            label, description, responsible,
                            input_json, idempotency_key, status,
                            output_json, error_text
                        ) VALUES (
                            $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,
                            $11,$12,$13,$14,$15,$16,$17,$18
                        )
                        """,
                        item.item_id,
                        plan.plan_id,
                        item.sequence_num,
                        item.runbook_id,
                        item.task_id,
                        json.dumps(list(item.depends_on)),
                        item.tool,
                        item.capability.value,
                        item.risk.value,
                        item.required,
                        item.label,
                        item.description,
                        item.responsible,
                        json.dumps(item.input_data),
                        item.idempotency_key,
                        item.status.value,
                        None if item.output_json is None else json.dumps(item.output_json),
                        item.error_text,
                    )

    # -------------------------------------------------------------------- load
    async def load(self, plan_id: str) -> Plan:
        """Rebuild a typed ``Plan`` from storage. Raises ``KeyError`` if absent."""
        async with self._pool.acquire() as conn:
            prow = await conn.fetchrow(
                "SELECT * FROM dev_plans WHERE plan_id = $1", plan_id
            )
            if prow is None:
                raise KeyError(f"plan {plan_id!r} not found")
            irows = await conn.fetch(
                "SELECT * FROM dev_plan_items WHERE plan_id = $1 ORDER BY sequence_num",
                plan_id,
            )
        return self._row_to_plan(prow, irows)

    async def get_by_question_id(self, question_id: str) -> Plan | None:
        """Correlate a poll response to its plan (UNIQUE question_id); None if absent."""
        async with self._pool.acquire() as conn:
            prow = await conn.fetchrow(
                "SELECT * FROM dev_plans WHERE question_id = $1", question_id
            )
            if prow is None:
                return None
            irows = await conn.fetch(
                "SELECT * FROM dev_plan_items WHERE plan_id = $1 ORDER BY sequence_num",
                prow["plan_id"],
            )
        return self._row_to_plan(prow, irows)

    @staticmethod
    def _row_to_plan(prow: Any, irows: Sequence[Any]) -> Plan:
        items = [
            PlanItem(
                item_id=r["item_id"],
                plan_id=r["plan_id"],
                sequence_num=r["sequence_num"],
                runbook_id=r["runbook_id"],
                task_id=r["task_id"],
                depends_on=_jsonb_loads(r["depends_on"]) or [],
                tool=r["tool"],
                capability=Capability(r["capability"]),
                risk=RiskLevel(r["risk"]),
                required=r["required"],
                label=r["label"],
                description=r["description"],
                responsible=r["responsible"],
                input_data=_jsonb_loads(r["input_json"]) or {},
                idempotency_key=r["idempotency_key"],
                status=ItemStatus(r["status"]),
                output_json=_jsonb_loads(r["output_json"]),
                error_text=r["error_text"],
            )
            for r in irows
        ]
        return Plan(
            plan_id=prow["plan_id"],
            session_id=prow["session_id"],
            run_id=prow["run_id"],
            question_id=prow["question_id"],
            runbook_id=prow["runbook_id"],
            runbook_version=prow["runbook_version"],
            title=prow["title"],
            summary=prow["summary"] or "",
            # 'explanation' is not persisted (markdown for the human, rebuilt on demand);
            # a placeholder keeps the model valid on load without inventing content.
            explanation="",
            responsible_profile=prow["responsible_profile"] or "",
            status=PlanStatus(prow["status"]),
            items=items,
        )

    # ------------------------------------------------------------ transitions
    async def transition_plan(
        self,
        plan_id: str,
        *,
        expected: Sequence[PlanStatus],
        new: PlanStatus,
    ) -> bool:
        """Guarded plan transition -> True iff a row matched the guard."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE dev_plans
                   SET status = $2, updated_at = NOW()
                 WHERE plan_id = $1
                   AND status = ANY($3::text[])
             RETURNING plan_id
                """,
                plan_id,
                new.value,
                [s.value for s in expected],
            )
        return row is not None

    async def transition_item(
        self,
        item_id: str,
        *,
        expected: Sequence[ItemStatus],
        new: ItemStatus,
        output: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> bool:
        """Guarded item transition -> True iff the guard matched.

        Records ``output``/``error`` when provided and always stamps
        ``updated_at`` (which, on entering EXECUTING, is the reconcile TTL clock).
        """
        set_output = output is not None
        set_error = error is not None
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE dev_plan_items
                   SET status = $2,
                       output_json = CASE WHEN $4 THEN $5::jsonb ELSE output_json END,
                       error_text  = CASE WHEN $6 THEN $7        ELSE error_text  END,
                       updated_at  = NOW()
                 WHERE item_id = $1
                   AND status = ANY($3::text[])
             RETURNING item_id
                """,
                item_id,
                new.value,
                [s.value for s in expected],
                set_output,
                json.dumps(output) if set_output else None,
                set_error,
                error if set_error else None,
            )
        return row is not None

    # -------------------------------------------------------------- approvals
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
        """Append exactly ONE audit row per approval (persists real item ids)."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO dev_plan_approvals (
                    approval_id, plan_id, run_id, approved_by,
                    approved_item_ids, high_risk_confirmed, response_value
                ) VALUES ($1,$2,$3,$4,$5::jsonb,$6::jsonb,$7::jsonb)
                """,
                str(uuid.uuid4()),
                plan_id,
                run_id,
                approved_by,
                json.dumps(list(approved_item_ids)),
                json.dumps(list(high_risk_confirmed_ids)),
                json.dumps(response_value),
            )

    # --------------------------------------------------------------- reconcile
    async def reconcile_orphans(
        self,
        plan_id: str,
        *,
        executing_ttl_s: float,
    ) -> list[str]:
        """Reconcile items stuck in EXECUTING beyond ``executing_ttl_s``.

        WRITE -> NEEDS_RECONFIRM, READ -> READY. One guarded UPDATE per capability
        class, deriving capability from the ``capability`` column, RETURNING the
        reconciled item ids. ``updated_at`` is the EXECUTING-since clock.
        """
        reconciled: list[str] = []
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                write_rows = await conn.fetch(
                    f"""
                    UPDATE dev_plan_items
                       SET status = $3, updated_at = NOW()
                     WHERE plan_id = $1
                       AND status = '{ItemStatus.EXECUTING.value}'
                       AND capability = '{Capability.WRITE.value}'
                       AND updated_at < NOW() - ($2 * INTERVAL '1 second')
                 RETURNING item_id
                    """,
                    plan_id,
                    executing_ttl_s,
                    ItemStatus.NEEDS_RECONFIRM.value,
                )
                read_rows = await conn.fetch(
                    f"""
                    UPDATE dev_plan_items
                       SET status = $3, updated_at = NOW()
                     WHERE plan_id = $1
                       AND status = '{ItemStatus.EXECUTING.value}'
                       AND capability = '{Capability.READ.value}'
                       AND updated_at < NOW() - ($2 * INTERVAL '1 second')
                 RETURNING item_id
                    """,
                    plan_id,
                    executing_ttl_s,
                    ItemStatus.READY.value,
                )
        reconciled.extend(r["item_id"] for r in write_rows)
        reconciled.extend(r["item_id"] for r in read_rows)
        return reconciled
