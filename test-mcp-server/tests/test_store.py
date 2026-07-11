"""Store canônico contra MySQL real (§16 / FID-02): CRUD, upsert de chave natural
composta, agregação em Python (cobertura/grade), auto-complete de run e ISOLAMENTO
por tenant (banco-por-tenant)."""

from __future__ import annotations

import pytest

# importado sob alias para o pytest não tentar coletar a classe (nome Test*).
from src.db.store import TestStore as Store

from .conftest import requires_mysql

pytestmark = [pytest.mark.integration, requires_mysql]


# ── Helpers estáticos (sem DB) ────────────────────────────────────────────────
def test_to_int_id_valid_and_invalid():
    assert Store._to_int_id("42") == 42
    assert Store._to_int_id(7) == 7
    with pytest.raises(ValueError):
        Store._to_int_id("nao_numerico")


def test_grade_boundaries():
    assert Store._grade(100.0, 100.0, {"critical": 1}) == "F"  # crítico -> F imediato
    assert Store._grade(100.0, 100.0, {}) == "A"
    assert Store._grade(80.0, 80.0, {}) == "B"
    assert Store._grade(70.0, 70.0, {}) == "C"
    assert Store._grade(60.0, 60.0, {}) == "D"
    assert Store._grade(10.0, 10.0, {}) == "F"


# ── Plans ─────────────────────────────────────────────────────────────────────
async def test_create_plan_returns_shape(store_a):
    plan = await store_a.create_plan("Meu Plano", "Escopo X", feature="feat-1")
    assert isinstance(plan["id"], int) and plan["id"] > 0
    assert plan["title"] == "Meu Plano"
    assert plan["scope"] == "Escopo X"  # plan_scope remapeado para scope
    assert plan["status"] == "active"


async def test_get_plan_none_when_absent(store_a):
    assert await store_a.get_plan(999999) is None


async def test_get_plan_counts_and_coverage(store_a, plan):
    sc = await store_a.add_scenario(plan["id"], "S", "happy_path", "s", "r")
    await store_a.record_result(plan["id"], sc["scenario_id"], "passed")
    await store_a.add_finding(plan["id"], "low", "t", "d")

    full = await store_a.get_plan(plan["id"])
    assert full["scenarios_count"] == 1
    assert full["results_count"] == 1
    assert full["findings_count"] == 1
    assert full["coverage"]["passed"] == 1
    assert full["scope"] == "Endpoint GET /api/items"  # remap plan_scope -> scope


async def test_list_plans_filter_and_order(store_a):
    await store_a.create_plan("A", "s1")
    b = await store_a.create_plan("B", "s2")
    # ordena por updated_at DESC → o último criado aparece primeiro
    listed = await store_a.list_plans()
    assert listed[0]["id"] == b["id"]
    assert all("scenarios_count" in p for p in listed)

    active = await store_a.list_plans(status="active")
    assert len(active) == 2
    assert await store_a.list_plans(status="archived") == []


# ── Scenarios ─────────────────────────────────────────────────────────────────
async def test_add_scenario_and_touch(store_a, plan):
    sc = await store_a.add_scenario(plan["id"], "Cenário", "auth", "passos", "esperado", priority="high")
    assert isinstance(sc["scenario_id"], int) and sc["scenario_id"] > 0
    assert sc["priority"] == "high"


async def test_get_scenarios_last_status_reflects_latest_result(store_a, plan):
    sc = await store_a.add_scenario(plan["id"], "S", "happy_path", "s", "r")
    sid = sc["scenario_id"]
    await store_a.record_result(plan["id"], sid, "failed")
    await store_a.record_result(plan["id"], sid, "passed")  # mais recente

    scenarios = await store_a.get_scenarios(plan["id"])
    assert len(scenarios) == 1
    assert scenarios[0]["last_status"] == "passed"  # último por executed_at


async def test_get_scenarios_without_results_is_null(store_a, plan):
    await store_a.add_scenario(plan["id"], "S", "happy_path", "s", "r")
    scenarios = await store_a.get_scenarios(plan["id"])
    assert scenarios[0]["last_status"] is None


# ── Checklists (upsert de chave natural composta + auto-complete) ─────────────
async def test_checklist_lifecycle_completes(store_a):
    created = await store_a.create_checklist(
        "Pré-deploy",
        "pre_deploy",
        items=[
            {"description": "item obrigatório", "required": True, "category": "q"},
            {"description": "item opcional", "required": False},
        ],
    )
    assert created["items_count"] == 2
    assert created["type"] == "pre_deploy"

    run = await store_a.start_run(created["checklist_id"], executor="qa")
    assert run["run_id"].startswith("run_")
    assert len(run["items"]) == 2

    for item in run["items"]:
        await store_a.check_item(run["run_id"], item["id"], "passed")

    status = await store_a.get_run_status(run["run_id"])
    assert status["status"] == "completed"  # todos os required verificados
    assert status["summary"]["passed"] == 2
    assert status["summary"]["pending"] == 0


async def test_check_item_upsert_is_idempotent(store_a):
    created = await store_a.create_checklist(
        "X", "custom", items=[{"description": "único", "required": True}]
    )
    run = await store_a.start_run(created["checklist_id"])
    item_id = run["items"][0]["id"]

    await store_a.check_item(run["run_id"], item_id, "failed", notes="1")
    await store_a.check_item(run["run_id"], item_id, "passed", notes="2")  # upsert (run_id,item_id)

    status = await store_a.get_run_status(run["run_id"])
    # ON DUPLICATE KEY: um único resultado por item; prevalece o último.
    assert status["summary"]["passed"] == 1
    assert status["summary"]["failed"] == 0
    assert status["items"][0]["result_status"] == "passed"
    assert status["items"][0]["notes"] == "2"


async def test_get_run_status_unknown_is_empty(store_a):
    assert await store_a.get_run_status("run_inexistente") == {}


async def test_check_item_unknown_run_still_records(store_a):
    # sem run correspondente, o upsert grava o resultado mas não auto-completa.
    result = await store_a.check_item("run_naoexiste", 1, "passed")
    assert result["run_id"] == "run_naoexiste"
    assert result["status"] == "passed"


# ── Findings + validação (agregação em Python) ────────────────────────────────
async def test_double_check_ready_when_all_passed(store_a, plan):
    sc = await store_a.add_scenario(plan["id"], "S", "happy_path", "s", "r")
    await store_a.record_result(plan["id"], sc["scenario_id"], "passed")
    result = await store_a.double_check(plan["id"])
    assert result["summary"]["ready_to_ship"] is True
    assert result["summary"]["total_scenarios"] == 1


async def test_double_check_blocked_by_failure_and_not_executed(store_a, plan):
    ok = await store_a.add_scenario(plan["id"], "ok", "happy_path", "s", "r")
    await store_a.record_result(plan["id"], ok["scenario_id"], "passed")
    ko = await store_a.add_scenario(plan["id"], "ko", "error", "s", "r")
    await store_a.record_result(plan["id"], ko["scenario_id"], "failed", actual_result="500")
    await store_a.add_scenario(plan["id"], "np", "boundary", "s", "r")  # não executado

    result = await store_a.double_check(plan["id"])
    assert result["summary"]["ready_to_ship"] is False
    assert result["summary"]["failed_count"] == 1
    assert result["summary"]["not_executed_count"] == 1
    assert result["failed_scenarios"][0]["actual_result"] == "500"


async def test_double_check_critical_finding_blocks(store_a, plan):
    sc = await store_a.add_scenario(plan["id"], "S", "happy_path", "s", "r")
    await store_a.record_result(plan["id"], sc["scenario_id"], "passed")
    await store_a.add_finding(plan["id"], "critical", "SQLi", "vulnerável")
    result = await store_a.double_check(plan["id"])
    assert result["summary"]["critical_findings"] == 1
    assert result["summary"]["ready_to_ship"] is False


async def test_get_validation_status_grade_and_findings(store_a, plan):
    sc = await store_a.add_scenario(plan["id"], "S", "happy_path", "s", "r")
    await store_a.record_result(plan["id"], sc["scenario_id"], "passed")
    await store_a.add_finding(plan["id"], "high", "H", "d")

    status = await store_a.get_validation_status(plan["id"])
    assert status["coverage_pct"] == 100.0
    assert status["pass_rate"] == 100.0
    assert status["findings_by_severity"] == {"high": 1}
    assert status["grade"] in {"A", "B"}


async def test_get_validation_status_empty_when_absent(store_a):
    assert await store_a.get_validation_status(999999) == {}


# ── Isolamento por tenant (banco-por-tenant, dual-db) ─────────────────────────
async def test_tenant_isolation(store_a, store_b):
    await store_a.create_plan("only-in-a", "escopo")
    assert len(await store_a.list_plans()) == 1
    # o tenant B tem SEU PRÓPRIO banco → não enxerga dados do A
    assert await store_b.list_plans() == []
