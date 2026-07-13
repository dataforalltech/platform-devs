"""Store do ledger contra MySQL real (§16 / FID-02): CRUD/upsert das 6 entidades,
merge-semantics de upsert (chave natural), JSON round-trip e ISOLAMENTO por tenant."""

from __future__ import annotations

import pytest

from .conftest import requires_mysql

pytestmark = [pytest.mark.integration, requires_mysql]


# ── Deployments (histórico append-only) ───────────────────────────────────────
async def test_deployment_history(store_a):
    d1 = await store_a.record_deployment(
        service="analytics",
        environment="dev",
        status="dispatched",
        ref="develop",
        repo="analytics",
        workflow="cd-dev.yml",
        detail={"dispatched": True, "hint": "x"},
    )
    assert isinstance(d1["id"], int) and d1["id"] > 0
    assert d1["service"] == "analytics" and d1["environment"] == "dev"
    assert d1["detail"] == {"dispatched": True, "hint": "x"}  # JSON round-trip

    await store_a.record_deployment(service="analytics", environment="hml", status="dispatched")
    assert len(await store_a.list_deployments()) == 2
    assert {d["environment"] for d in await store_a.list_deployments(service="analytics")} == {"dev", "hml"}
    assert len(await store_a.list_deployments(environment="dev")) == 1

    got = await store_a.get_deployment(d1["id"])
    assert got is not None and got["workflow"] == "cd-dev.yml"
    assert await store_a.get_deployment(999999) is None


# ── Pull Requests (upsert por (repo, number) + merge-semantics) ───────────────
async def test_pull_request_upsert_merge_semantics(store_a):
    first = await store_a.upsert_pull_request(
        repo="svc", number=7, title="feat: x", base="develop", head="feature/x", url="u", state="open"
    )
    assert first["repo"] == "svc" and first["number"] == 7 and first["state"] == "open"

    # merge_pr grava só state='merged'; _prune preserva título/base/head anteriores.
    merged = await store_a.upsert_pull_request(repo="svc", number=7, state="merged")
    assert merged["state"] == "merged"
    assert merged["title"] == "feat: x"  # PRESERVADO (merge semantics)
    assert merged["head"] == "feature/x"

    prs = await store_a.list_pull_requests()
    assert len(prs) == 1  # ON DUPLICATE KEY: uma linha só (não duplica)
    assert await store_a.list_pull_requests(repo="svc", state="merged") != []
    assert await store_a.list_pull_requests(state="open") == []


# ── Branches (upsert por (repo, branch)) ──────────────────────────────────────
async def test_branch_upsert(store_a):
    b = await store_a.upsert_branch(repo="svc", branch="feature/x", from_ref="develop", status="created")
    assert b["repo"] == "svc" and b["branch"] == "feature/x" and b["status"] == "created"

    # re-upsert mesma (repo, branch) → não duplica
    await store_a.upsert_branch(repo="svc", branch="feature/x", status="stale")
    branches = await store_a.list_branches(repo="svc")
    assert len(branches) == 1 and branches[0]["status"] == "stale"
    assert branches[0]["from_ref"] == "develop"  # preservado


# ── Workflow Runs (upsert por (repo, run_id); run_id VARCHAR aceita id do GitHub) ─
async def test_workflow_run_upsert_big_run_id(store_a):
    big = "10000000000"  # > INT range → só cabe por ser VARCHAR
    r = await store_a.upsert_workflow_run(
        repo="svc", run_id=big, workflow="CD DEV", status="in_progress", detail={"a": 1}
    )
    assert r["run_id"] == big and r["status"] == "in_progress"
    assert r["detail"] == {"a": 1}

    # refresh do mesmo run → upsert, não duplica; conclusion nova, detail preserva merge
    refreshed = await store_a.upsert_workflow_run(
        repo="svc", run_id=big, status="completed", conclusion="success"
    )
    assert refreshed["status"] == "completed" and refreshed["conclusion"] == "success"
    assert refreshed["workflow"] == "CD DEV"  # preservado

    runs = await store_a.list_workflow_runs()
    assert len(runs) == 1
    assert await store_a.list_workflow_runs(repo="svc", status="completed") != []


# ── Repos (upsert por chave natural única `repo`) ─────────────────────────────
async def test_repo_upsert(store_a):
    r = await store_a.upsert_repo(
        repo="svc", config={"image_name": "svc", "registry": "r"}, status="configured"
    )
    assert r["repo"] == "svc" and r["status"] == "configured"
    assert r["config"] == {"image_name": "svc", "registry": "r"}

    await store_a.upsert_repo(repo="svc", status="partial")
    repos = await store_a.list_repos()
    assert len(repos) == 1 and repos[0]["status"] == "partial"
    assert repos[0]["config"] == {"image_name": "svc", "registry": "r"}  # preservado


# ── Events (histórico append-only genérico) ───────────────────────────────────
async def test_event_history(store_a):
    e1 = await store_a.record_event(kind="clone", target="org/svc", status="cloned", detail={"path": "/x"})
    e2 = await store_a.record_event(kind="acr_build", target="img:v1", status="success")
    assert e1["id"] != e2["id"]
    assert e1["kind"] == "clone" and e1["detail"] == {"path": "/x"}

    assert len(await store_a.list_events()) == 2
    assert {e["id"] for e in await store_a.list_events(kind="clone")} == {e1["id"]}
    assert {e["id"] for e in await store_a.list_events(target="img:v1")} == {e2["id"]}


# ── Isolamento por tenant (banco-por-tenant, dual-db) ─────────────────────────
async def test_tenant_isolation(store_a, store_b):
    await store_a.record_deployment(service="only-in-a", environment="dev", status="dispatched")
    await store_a.upsert_repo(repo="svc-a", status="configured")

    assert len(await store_a.list_deployments()) == 1
    # o tenant B tem SEU PRÓPRIO banco → não enxerga nada do A
    assert await store_b.list_deployments() == []
    assert await store_b.list_repos() == []
    assert await store_b.list_pull_requests() == []
