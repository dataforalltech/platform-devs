"""Store canônico contra MySQL real (§16 / FID-02): CRUD das 5 entidades, upsert de
chave natural (quality gate por service), soft-delete e ISOLAMENTO por tenant."""

from __future__ import annotations

import pytest

from .conftest import requires_mysql

pytestmark = [pytest.mark.integration, requires_mysql]


# ── Test Plans ────────────────────────────────────────────────────────────────
async def test_test_plan_crud(store_a):
    saved = await store_a.save_test_plan(
        feature="login", content={"objectives": ["ok"]}, scope="full", team="qa"
    )
    assert isinstance(saved["id"], int) and saved["id"] > 0
    assert saved["feature"] == "login"
    assert saved["content"] == {"objectives": ["ok"]}  # JSON round-trip

    got = await store_a.get_test_plan(saved["id"])
    assert got is not None and got["team"] == "qa"

    updated = await store_a.update_test_plan(saved["id"], status="approved", scope="partial")
    assert updated is not None and updated["status"] == "approved" and updated["scope"] == "partial"

    listed = await store_a.list_test_plans(feature="login")
    assert len(listed) == 1
    assert await store_a.list_test_plans(status="approved") != []

    assert await store_a.delete_test_plan(saved["id"]) == 1
    assert await store_a.get_test_plan(saved["id"]) is None
    assert await store_a.list_test_plans() == []


async def test_test_plan_get_missing_returns_none(store_a):
    assert await store_a.get_test_plan(999999) is None
    assert await store_a.update_test_plan(999999, status="x") is None
    assert await store_a.delete_test_plan(999999) == 0


# ── Test Cases ────────────────────────────────────────────────────────────────
async def test_test_case_crud(store_a):
    saved = await store_a.save_test_case(
        feature="checkout",
        title="paga com cartão",
        steps=[{"step": 1, "action": "abrir"}],
        test_type="e2e",
        priority="high",
        preconditions=["logado"],
        test_data={"card": "4111"},
    )
    assert saved["id"] > 0
    assert saved["steps"] == [{"step": 1, "action": "abrir"}]
    assert saved["preconditions"] == ["logado"]
    assert saved["test_data"] == {"card": "4111"}

    updated = await store_a.update_test_case(saved["id"], priority="medium", status="passed")
    assert updated["priority"] == "medium" and updated["status"] == "passed"

    assert {c["id"] for c in await store_a.list_test_cases(test_type="e2e")} == {saved["id"]}
    assert await store_a.list_test_cases(feature="checkout", status="passed") != []

    assert await store_a.delete_test_case(saved["id"]) == 1
    assert await store_a.get_test_case(saved["id"]) is None


# ── Bug Reports ───────────────────────────────────────────────────────────────
async def test_bug_report_crud(store_a):
    saved = await store_a.save_bug_report(
        title="500 no submit",
        severity="P1",
        impact="critical",
        frequency="always",
        score=16.0,
        steps=["abrir", "enviar"],
        description="stacktrace",
        status="open",
    )
    assert saved["id"] > 0
    assert saved["severity"] == "P1" and saved["score"] == 16.0
    assert saved["steps"] == ["abrir", "enviar"]

    updated = await store_a.update_bug_status(saved["id"], "closed")
    assert updated["status"] == "closed"

    assert {b["id"] for b in await store_a.list_bug_reports(severity="P1")} == {saved["id"]}
    assert await store_a.list_bug_reports(status="closed") != []

    assert await store_a.delete_bug_report(saved["id"]) == 1
    assert await store_a.get_bug_report(saved["id"]) is None


# ── Quality Gates (upsert por service) ────────────────────────────────────────
async def test_quality_gate_upsert_by_service(store_a):
    first = await store_a.set_quality_gate("svc", {"coverage": 80}, status="active")
    assert first["service"] == "svc"
    assert first["thresholds"] == {"coverage": 80}

    # mesmo service → upsert (não duplica), sobrescreve thresholds/status
    second = await store_a.set_quality_gate("svc", {"coverage": 90}, status="blocking")
    assert second["thresholds"] == {"coverage": 90} and second["status"] == "blocking"

    gates = await store_a.list_quality_gates()
    assert len(gates) == 1  # ON DUPLICATE KEY: uma linha só

    got = await store_a.get_quality_gate("svc")
    assert got is not None and got["thresholds"] == {"coverage": 90}
    assert await store_a.get_quality_gate("inexistente") is None

    assert await store_a.delete_quality_gate("svc") == 1
    assert await store_a.get_quality_gate("svc") is None


# ── Artifacts (histórico append-only) ─────────────────────────────────────────
async def test_artifact_history_append_only(store_a):
    a1 = await store_a.save_artifact(
        kind="playwright", target="login", content="test('x', ...)", framework="playwright"
    )
    a2 = await store_a.save_artifact(kind="k6", target="/api", content="export default ...", meta={"vus": 10})
    assert a1["id"] != a2["id"]
    assert a2["meta"] == {"vus": 10}
    assert a2["content"] == "export default ..."  # texto livre, não JSON

    assert {a["id"] for a in await store_a.list_artifacts(kind="playwright")} == {a1["id"]}
    assert {a["id"] for a in await store_a.list_artifacts(target="/api")} == {a2["id"]}
    assert len(await store_a.list_artifacts()) == 2

    got = await store_a.get_artifact(a1["id"])
    assert got is not None and got["kind"] == "playwright"

    assert await store_a.delete_artifact(a1["id"]) == 1
    assert await store_a.get_artifact(a1["id"]) is None
    assert len(await store_a.list_artifacts()) == 1


# ── Isolamento por tenant (banco-por-tenant, dual-db) ─────────────────────────
async def test_tenant_isolation(store_a, store_b):
    await store_a.save_test_plan(feature="only-in-a", content={})
    await store_a.set_quality_gate("svc-a", {"x": 1})

    assert len(await store_a.list_test_plans()) == 1
    # o tenant B tem SEU PRÓPRIO banco → não enxerga dados do A
    assert await store_b.list_test_plans() == []
    assert await store_b.list_quality_gates() == []
    assert await store_b.get_quality_gate("svc-a") is None
