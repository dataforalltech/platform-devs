"""Store canônico contra MySQL real (§16 / FID-02): CRUD, upsert de chave natural,
soft-delete, overview e ISOLAMENTO por tenant (banco-por-tenant)."""

from __future__ import annotations

import pytest

from src.db.store import DEFAULT_GATES

from .conftest import requires_mysql

pytestmark = [pytest.mark.integration, requires_mysql]


# ── Pipelines ─────────────────────────────────────────────────────────────────
async def test_register_creates_then_updates(store_a):
    created = await store_a.register_pipeline("svc-a", "org/svc-a", "develop")
    assert created["action"] == "created"
    assert created["pipeline"]["service"] == "svc-a"
    assert isinstance(created["pipeline"]["gates_config"], dict)  # JSON parseado
    assert created["pipeline"]["gates_config"] == DEFAULT_GATES

    updated = await store_a.register_pipeline("svc-a", "org/svc-a-renamed")
    assert updated["action"] == "updated"
    assert updated["pipeline"]["repo"] == "org/svc-a-renamed"
    # re-register preserva ambiente e não reseta gates
    assert updated["pipeline"]["current_env"] == "dev"


async def test_get_pipeline_none_when_absent(store_a):
    assert await store_a.get_pipeline("nao-existe") is None


async def test_get_pipeline_includes_recent_promotions(store_a):
    await store_a.register_pipeline("svc", "o/svc")
    await store_a.add_promotion(
        "svc", "dev", "homol", "u", None, {}, "homol", "pending"
    )
    pipeline = await store_a.get_pipeline("svc")
    assert len(pipeline["recent_promotions"]) == 1


async def test_list_pipelines_filters(store_a):
    await store_a.register_pipeline("a", "o/a")
    await store_a.register_pipeline("b", "o/b")
    await store_a.update_pipeline_env("b", "homol")
    await store_a.block_pipeline("a", "risco", "ops")

    all_p = await store_a.list_pipelines()
    assert [p["service"] for p in all_p] == ["a", "b"]  # ordenado por service

    assert {p["service"] for p in await store_a.list_pipelines(env="homol")} == {"b"}
    assert {p["service"] for p in await store_a.list_pipelines(status="blocked")} == {
        "a"
    }
    assert {p["service"] for p in await store_a.list_pipelines(status="active")} == {
        "b"
    }


async def test_block_and_set_config(store_a):
    await store_a.register_pipeline("svc", "o/svc")
    blocked = await store_a.block_pipeline("svc", "motivo", "ana")
    assert blocked["blocked"] == 1
    assert blocked["block_reason"] == "motivo"

    updated = await store_a.set_gates_config("svc", {"homol": ["qa_tests"]})
    assert updated["gates_config"] == {"homol": ["qa_tests"]}


# ── Promotions ────────────────────────────────────────────────────────────────
async def test_promotion_lifecycle(store_a):
    await store_a.register_pipeline("svc", "o/svc")
    pid = await store_a.add_promotion(
        "svc",
        "dev",
        "homol",
        "user",
        "reason",
        {"qa_tests": True},
        "homol",
        "pending_human_approval",
        pr_number=7,
        pr_url="http://pr/7",
    )
    assert isinstance(pid, int) and pid > 0

    got = await store_a.get_promotion(pid)
    assert got["status"] == "pending_human_approval"
    assert got["pr_number"] == 7

    approved = await store_a.approve_promotion(pid, "boss")
    assert approved["status"] == "pending_external_execution"
    assert approved["approved_by"] == "boss"
    assert approved["approved_at"] is not None
    assert approved["completed_at"] is None

    await store_a.complete_promotion(pid, "success")
    assert (await store_a.get_promotion(pid))["status"] == "success"

    assert await store_a.get_promotion(999999) is None
    assert await store_a.approve_promotion(999999, "x") is None


async def test_promotion_history_scoping(store_a):
    await store_a.register_pipeline("s1", "o/s1")
    await store_a.register_pipeline("s2", "o/s2")
    await store_a.add_promotion("s1", "dev", "homol", "u", None, {}, "homol", "pending")
    await store_a.add_promotion("s2", "dev", "homol", "u", None, {}, "homol", "pending")

    assert len(await store_a.get_promotion_history()) == 2
    assert len(await store_a.get_promotion_history("s1")) == 1
    assert len(await store_a.get_promotion_history(limit=1)) == 1


# ── Gates (upsert por chave natural + soft-delete) ────────────────────────────
async def test_gate_upsert_is_idempotent(store_a):
    await store_a.register_pipeline("svc", "o/svc")
    await store_a.upsert_gate("svc", "dev", "qa_tests", passed=False, details="1")
    row = await store_a.upsert_gate("svc", "dev", "qa_tests", passed=True, details="2")
    assert row["passed"] == 1
    gates = await store_a.get_gates("svc", "dev")
    assert len(gates) == 1  # ON DUPLICATE KEY: não duplicou
    assert gates[0]["details"] == "2"


async def test_clear_gates_soft_delete_and_reactivate(store_a):
    await store_a.register_pipeline("svc", "o/svc")
    await store_a.upsert_gate("svc", "dev", "qa_tests", passed=True)
    await store_a.upsert_gate("svc", "dev", "security_scan", passed=True)

    cleared = await store_a.clear_gates("svc", "dev")
    assert cleared == 2
    assert await store_a.get_gates("svc", "dev") == []

    # re-adicionar reativa a linha soft-deletada (mesma chave única)
    await store_a.upsert_gate("svc", "dev", "qa_tests", passed=True)
    assert len(await store_a.get_gates("svc", "dev")) == 1


async def test_overview_counts(store_a):
    await store_a.register_pipeline("s1", "o/s1")
    await store_a.register_pipeline("s2", "o/s2")
    await store_a.update_pipeline_env("s2", "homol")
    await store_a.block_pipeline("s1", "x", "ops")
    await store_a.upsert_gate("s2", "homol", "qa_tests", passed=False)

    ov = await store_a.get_pipeline_overview()
    assert ov["total_services"] == 2
    assert ov["by_env"]["dev"]["blocked"] == 1
    assert ov["by_env"]["homol"]["active"] == 1
    assert ov["services_with_failed_gates"] == [
        {"service": "s2", "env": "homol", "failed": 1}
    ]


# ── Isolamento por tenant (banco-por-tenant, dual-db) ─────────────────────────
async def test_tenant_isolation(store_a, store_b):
    await store_a.register_pipeline("only-in-a", "o/a")
    assert len(await store_a.list_pipelines()) == 1
    # o tenant B tem SEU PRÓPRIO banco → não enxerga dados do A
    assert await store_b.list_pipelines() == []
    assert await store_b.get_pipeline("only-in-a") is None
