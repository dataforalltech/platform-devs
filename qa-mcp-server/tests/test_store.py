"""Store canônico contra MySQL real (§16 / FID-02): Create + Read do log append-only,
filtros de list_runs, (de)serialização JSON e ISOLAMENTO por tenant (banco-por-tenant)."""

from __future__ import annotations

import pytest

from .conftest import requires_mysql

pytestmark = [pytest.mark.integration, requires_mysql]


# ── save_run + list_runs ──────────────────────────────────────────────────────
async def test_save_run_returns_id(store_a):
    run_id = await store_a.save_run(
        run_type="unit",
        status="passed",
        summary={"passed": 3, "failed": 0},
        details={"output": "ok"},
        repo_path="/repo",
        framework="pytest",
        duration_ms=1500,
    )
    assert isinstance(run_id, int) and run_id > 0


async def test_list_runs_roundtrips_json(store_a):
    await store_a.save_run(
        run_type="security",
        status="failed",
        summary={"high": 2, "medium": 1, "low": 0},
        details={"findings": ["a", "b"]},
        repo_path="/repo",
    )
    rows = await store_a.list_runs(repo_path="/repo")
    assert len(rows) == 1
    row = rows[0]
    # summary/details voltam como dict (JSON parseado), não string
    assert row["summary"] == {"high": 2, "medium": 1, "low": 0}
    assert row["details"] == {"findings": ["a", "b"]}
    assert row["run_type"] == "security"
    assert row["status"] == "failed"
    assert isinstance(row["started_at"], str)  # coluna de negócio preservada


async def test_list_runs_filters_by_repo_and_type(store_a):
    await store_a.save_run("unit", "passed", {"passed": 1}, {}, repo_path="/a")
    await store_a.save_run("linter", "passed", {"errors": 0}, {}, repo_path="/a")
    await store_a.save_run("unit", "passed", {"passed": 2}, {}, repo_path="/b")

    assert len(await store_a.list_runs()) == 3
    assert len(await store_a.list_runs(repo_path="/a")) == 2
    assert len(await store_a.list_runs(repo_path="/a", run_type="unit")) == 1
    assert len(await store_a.list_runs(run_type="unit")) == 2


async def test_list_runs_orders_recent_first_and_limits(store_a):
    for i in range(5):
        await store_a.save_run("unit", "passed", {"n": i}, {}, repo_path="/repo")
    rows = await store_a.list_runs(repo_path="/repo", limit=2)
    assert len(rows) == 2
    # mais recente primeiro: o último inserido (n=4) vem antes de n=3
    assert rows[0]["summary"]["n"] == 4
    assert rows[1]["summary"]["n"] == 3


async def test_list_runs_appends_history_not_upsert(store_a):
    # log append-only: múltiplas linhas por (repo_path, run_type) são o histórico
    await store_a.save_run("unit", "passed", {"passed": 1}, {}, repo_path="/repo")
    await store_a.save_run("unit", "failed", {"passed": 0}, {}, repo_path="/repo")
    rows = await store_a.list_runs(repo_path="/repo", run_type="unit")
    assert len(rows) == 2  # não sobrescreveu — histórico


async def test_save_run_nullable_repo_path(store_a):
    # run_e2e_tests grava com repo_path=None (base_url viaja em details)
    run_id = await store_a.save_run("e2e", "passed", {"passed": 2}, {"base_url": "http://x"})
    assert run_id > 0
    rows = await store_a.list_runs(run_type="e2e")
    assert len(rows) == 1
    assert rows[0]["repo_path"] is None


# ── Isolamento por tenant (banco-por-tenant, dual-db) ─────────────────────────
async def test_tenant_isolation(store_a, store_b):
    await store_a.save_run("unit", "passed", {"passed": 1}, {}, repo_path="/only-in-a")
    assert len(await store_a.list_runs()) == 1
    # o tenant B tem SEU PRÓPRIO banco → não enxerga dados do A
    assert await store_b.list_runs() == []
    assert await store_b.list_runs(repo_path="/only-in-a") == []
