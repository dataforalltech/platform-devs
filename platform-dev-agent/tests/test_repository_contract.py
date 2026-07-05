"""Contract / PARITY suite for PlanRepository.

One suite, two backends, proven identical:

- ``InMemoryPlanRepository`` — always exercised.
- ``PostgresPlanRepository`` — exercised only when ``DEV_PG_DSN`` is set in the
  environment; otherwise every PG case is ``pytest.skip``-ped. The PG fixture
  connects via ``asyncpg.create_pool(DEV_PG_DSN)``, applies
  ``migrations/0001_dev_plans.sql``, yields, then truncates the tables it owns.

The ``repo`` fixture is parametrized over both, so each test below runs against
both stores and asserts the SAME guarded-transition behaviour (the whole point
of the ABC): create/load round-trip, guarded transitions (wrong expected ->
False no-op, valid -> True, repeated -> False), orphan reconciliation, and
question-id correlation.

Forcing "beyond the EXECUTING TTL":
- InMemory keeps ``executing_since`` (monotonic) per stored item; the fixture
  exposes a hook that back-dates it so ``reconcile_orphans`` fires deterministically.
- Postgres uses the ``updated_at`` column; the hook back-dates it via a direct
  UPDATE. Both then call ``reconcile_orphans(..., executing_ttl_s=...)`` the same way.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.dev_agent.models.plan import (
    Capability,
    ItemStatus,
    Plan,
    PlanItem,
    PlanStatus,
    RiskLevel,
)
from app.dev_agent.plan.repository import InMemoryPlanRepository, PlanRepository
from app.dev_agent.plan.repository_pg import PostgresPlanRepository

_MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "dev_agent"
    / "plan"
    / "migrations"
    / "0001_dev_plans.sql"
)


# --------------------------------------------------------------------- helpers
def _make_plan(*, question_id: str = "plan_contract_0001") -> Plan:
    """A 2-item plan: one WRITE item and one READ item (for the reconcile split)."""
    plan = Plan(
        session_id="s-contract",
        run_id="run-contract",
        question_id=question_id,
        runbook_id="rb-contract",
        runbook_version="1.0.0",
        title="contract plan",
        summary="parity fixture",
        explanation="e",
        responsible_profile="devops",
        items=[],
    )
    plan.items = [
        PlanItem(
            plan_id=plan.plan_id,
            sequence_num=1,
            runbook_id="rb-contract",
            task_id="w",
            depends_on=[],
            tool="config-mcp.set_config",
            capability=Capability.WRITE,
            risk=RiskLevel.MEDIUM,
            required=True,
            label="write step",
            description="a write",
            responsible="devops",
            input_data={"key": "v"},
        ),
        PlanItem(
            plan_id=plan.plan_id,
            sequence_num=2,
            runbook_id="rb-contract",
            task_id="r",
            depends_on=["w"],
            tool="qa-mcp.run_tests",
            capability=Capability.READ,
            risk=RiskLevel.LOW,
            required=False,
            label="read step",
            responsible="qa-engineer",
            input_data={"suite": "unit"},
        ),
    ]
    return plan


class _BackdateHook:
    """Uniform way to force an EXECUTING item "beyond the TTL" for both stores."""

    def __init__(self, repo: PlanRepository) -> None:
        self._repo = repo

    async def backdate_executing(self, item_id: str, *, seconds: float) -> None:
        if isinstance(self._repo, InMemoryPlanRepository):
            # Monotonic clock: push executing_since into the past.
            import time

            self._repo._items[item_id].executing_since = time.monotonic() - seconds
        else:
            # Postgres: push updated_at into the past directly.
            async with self._repo._pool.acquire() as conn:  # type: ignore[attr-defined]
                await conn.execute(
                    "UPDATE dev_plan_items"
                    " SET updated_at = NOW() - ($2 * INTERVAL '1 second')"
                    " WHERE item_id = $1",
                    item_id,
                    seconds,
                )


# -------------------------------------------------------------------- fixtures
@pytest.fixture
async def inmemory_repo() -> InMemoryPlanRepository:
    return InMemoryPlanRepository()


@pytest.fixture
async def postgres_repo():
    dsn = os.getenv("DEV_PG_DSN")
    if not dsn:
        pytest.skip("DEV_PG_DSN not set — Postgres parity checks skipped")
    import asyncpg

    pool = await asyncpg.create_pool(dsn)
    ddl = _MIGRATION.read_text(encoding="utf-8")
    async with pool.acquire() as conn:
        await conn.execute(ddl)
        # Start from a clean slate; CASCADE handles items/approvals.
        await conn.execute("TRUNCATE dev_plans CASCADE")
    try:
        yield PostgresPlanRepository(pool)
    finally:
        async with pool.acquire() as conn:
            await conn.execute("TRUNCATE dev_plans CASCADE")
        await pool.close()


@pytest.fixture(params=["inmemory", "postgres"])
def repo(request) -> PlanRepository:
    """Parametrized: every test runs against BOTH backends (PG skipped w/o DSN).

    Kept SYNC on purpose: it only resolves the underlying (async) backend fixture
    via ``getfixturevalue``. An async wrapper here would re-enter the running loop
    (``This event loop is already running``); the resolved fixtures are still the
    genuine async ones, awaited by pytest-asyncio in their own setup.
    """
    return request.getfixturevalue(f"{request.param}_repo")


# ----------------------------------------------------------------------- tests
async def test_create_and_load_round_trip(repo: PlanRepository) -> None:
    plan = _make_plan()
    await repo.create(plan)

    loaded = await repo.load(plan.plan_id)
    assert loaded.plan_id == plan.plan_id
    assert loaded.status is PlanStatus.PENDING
    assert loaded.runbook_version == "1.0.0"
    assert [i.task_id for i in loaded.items] == ["w", "r"]

    w, r = loaded.items
    assert w.capability is Capability.WRITE
    assert w.risk is RiskLevel.MEDIUM
    assert w.required is True
    assert w.input_data == {"key": "v"}
    assert r.capability is Capability.READ
    assert r.required is False
    assert r.depends_on == ["w"]
    assert r.idempotency_key  # round-tripped, non-empty


async def test_load_missing_raises_keyerror(repo: PlanRepository) -> None:
    with pytest.raises(KeyError):
        await repo.load("does-not-exist")


async def test_get_by_question_id(repo: PlanRepository) -> None:
    assert await repo.get_by_question_id("nope") is None

    plan = _make_plan(question_id="plan_by_qid_0001")
    await repo.create(plan)

    found = await repo.get_by_question_id("plan_by_qid_0001")
    assert found is not None
    assert found.plan_id == plan.plan_id


async def test_transition_plan_guarded(repo: PlanRepository) -> None:
    plan = _make_plan()
    await repo.create(plan)

    # Wrong expected -> no-op / False, status unchanged.
    assert await repo.transition_plan(
        plan.plan_id, expected=[PlanStatus.DONE], new=PlanStatus.FAILED
    ) is False
    assert (await repo.load(plan.plan_id)).status is PlanStatus.PENDING

    # Valid guard -> True.
    assert await repo.transition_plan(
        plan.plan_id, expected=[PlanStatus.PENDING], new=PlanStatus.EXECUTING
    ) is True
    assert (await repo.load(plan.plan_id)).status is PlanStatus.EXECUTING

    # Idempotency: the SAME transition again no longer matches -> False.
    assert await repo.transition_plan(
        plan.plan_id, expected=[PlanStatus.PENDING], new=PlanStatus.EXECUTING
    ) is False
    assert (await repo.load(plan.plan_id)).status is PlanStatus.EXECUTING


async def test_transition_item_guarded_and_records_output(repo: PlanRepository) -> None:
    plan = _make_plan()
    await repo.create(plan)
    item_id = plan.items[1].item_id  # the READ item

    # Wrong expected -> no-op / False.
    assert await repo.transition_item(
        item_id, expected=[ItemStatus.DONE], new=ItemStatus.ERROR
    ) is False

    # Valid PENDING -> EXECUTING.
    assert await repo.transition_item(
        item_id, expected=[ItemStatus.PENDING], new=ItemStatus.EXECUTING
    ) is True

    # EXECUTING -> DONE, recording output.
    assert await repo.transition_item(
        item_id,
        expected=[ItemStatus.EXECUTING],
        new=ItemStatus.DONE,
        output={"passed": 1},
    ) is True

    # Idempotency: repeating the EXECUTING->DONE guard no longer matches.
    assert await repo.transition_item(
        item_id, expected=[ItemStatus.EXECUTING], new=ItemStatus.DONE
    ) is False

    loaded = await repo.load(plan.plan_id)
    done_item = {i.item_id: i for i in loaded.items}[item_id]
    assert done_item.status is ItemStatus.DONE
    assert done_item.output_json == {"passed": 1}


async def test_transition_item_records_error(repo: PlanRepository) -> None:
    plan = _make_plan()
    await repo.create(plan)
    item_id = plan.items[0].item_id

    await repo.transition_item(
        item_id, expected=[ItemStatus.PENDING], new=ItemStatus.EXECUTING
    )
    assert await repo.transition_item(
        item_id,
        expected=[ItemStatus.EXECUTING],
        new=ItemStatus.ERROR,
        error="boom",
    ) is True

    loaded = await repo.load(plan.plan_id)
    errored = {i.item_id: i for i in loaded.items}[item_id]
    assert errored.status is ItemStatus.ERROR
    assert errored.error_text == "boom"


async def test_record_approval_persists_one_row(repo: PlanRepository) -> None:
    plan = _make_plan()
    await repo.create(plan)

    # Should not raise; persists exactly one audit row with the real item ids.
    await repo.record_approval(
        plan_id=plan.plan_id,
        approved_by="human@example.com",
        approved_item_ids=[plan.items[0].item_id],
        high_risk_confirmed_ids=[],
        run_id="run-contract",
        response_value=["write step"],
    )

    # In-memory exposes an introspection helper; assert the row landed there.
    if isinstance(repo, InMemoryPlanRepository):
        rows = repo.approvals_for(plan.plan_id)
        assert len(rows) == 1
        assert rows[0].approved_item_ids == [plan.items[0].item_id]


async def test_reconcile_orphans_write_and_read(repo: PlanRepository) -> None:
    """WRITE EXECUTING beyond TTL -> NEEDS_RECONFIRM; READ -> READY."""
    plan = _make_plan()
    await repo.create(plan)
    write_id = plan.items[0].item_id  # capability WRITE
    read_id = plan.items[1].item_id  # capability READ

    # Claim both into EXECUTING.
    assert await repo.transition_item(
        write_id, expected=[ItemStatus.PENDING], new=ItemStatus.EXECUTING
    ) is True
    assert await repo.transition_item(
        read_id, expected=[ItemStatus.PENDING], new=ItemStatus.EXECUTING
    ) is True

    # Force both "beyond the TTL" uniformly across backends.
    hook = _BackdateHook(repo)
    await hook.backdate_executing(write_id, seconds=120)
    await hook.backdate_executing(read_id, seconds=120)

    reconciled = await repo.reconcile_orphans(plan.plan_id, executing_ttl_s=60)
    assert set(reconciled) == {write_id, read_id}

    loaded = {i.item_id: i for i in (await repo.load(plan.plan_id)).items}
    assert loaded[write_id].status is ItemStatus.NEEDS_RECONFIRM  # write not re-run blindly
    assert loaded[read_id].status is ItemStatus.READY  # read is re-claimable

    # Idempotent: nothing left in EXECUTING -> a second reconcile returns [].
    assert await repo.reconcile_orphans(plan.plan_id, executing_ttl_s=60) == []


async def test_reconcile_orphans_ignores_fresh_executing(repo: PlanRepository) -> None:
    """An EXECUTING item younger than the TTL is left untouched."""
    plan = _make_plan()
    await repo.create(plan)
    write_id = plan.items[0].item_id

    await repo.transition_item(
        write_id, expected=[ItemStatus.PENDING], new=ItemStatus.EXECUTING
    )
    # No back-dating: a large TTL means it is NOT yet an orphan.
    reconciled = await repo.reconcile_orphans(plan.plan_id, executing_ttl_s=3600)
    assert reconciled == []
    loaded = {i.item_id: i for i in (await repo.load(plan.plan_id)).items}
    assert loaded[write_id].status is ItemStatus.EXECUTING
