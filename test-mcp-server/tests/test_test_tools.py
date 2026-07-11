"""Testes das tools reais do test-mcp (plan/scenario/checklist/validation).

Exercitam a lógica de negócio preservada em src/tools/ (async) sobre o ``store``
tenant-scoped ligado a um MySQL real (§16 / FID-02) — banco nunca mockado.
"""

from __future__ import annotations

import pytest

from src.tools.checklist_tool import (
    check_item,
    create_checklist,
    get_run_status,
    run_checklist,
)
from src.tools.plan_tool import create_test_plan, get_test_plan, list_test_plans
from src.tools.scenario_tool import add_scenario, generate_scenarios, record_result
from src.tools.validation_tool import add_finding, double_check, get_validation_status

from .conftest import requires_mysql

pytestmark = [pytest.mark.integration, requires_mysql]


# ── plan_tool ─────────────────────────────────────────────────────────────────
async def test_create_plan_ok(store):
    result = await create_test_plan(store, title="Meu Plano", scope="Feature X")
    assert result["title"] == "Meu Plano"
    assert result["status"] == "active"
    assert isinstance(result["id"], int) and result["id"] > 0


async def test_create_plan_missing_fields(store):
    assert (await create_test_plan(store, title="", scope="X"))["error"] == "ValidationError"


async def test_get_plan_ok(store, plan):
    result = await get_test_plan(store, plan_id=plan["id"])
    assert result["id"] == plan["id"]
    assert "coverage" in result


async def test_get_plan_not_found(store):
    assert (await get_test_plan(store, plan_id="999999"))["error"] == "not_found"


async def test_get_plan_missing_id(store):
    assert (await get_test_plan(store, plan_id=""))["error"] == "ValidationError"


async def test_get_plan_include_scenarios(store, plan):
    result = await get_test_plan(store, plan_id=plan["id"], include_scenarios=True)
    assert isinstance(result["scenarios"], list)


async def test_list_plans(store):
    await create_test_plan(store, title="A", scope="s1")
    await create_test_plan(store, title="B", scope="s2")
    assert (await list_test_plans(store))["count"] >= 2


async def test_list_plans_invalid_status(store):
    assert (await list_test_plans(store, status="invalido"))["error"] == "ValidationError"


async def test_list_plans_filtered_by_status(store):
    await create_test_plan(store, title="A", scope="s1")
    result = await list_test_plans(store, status="active")
    assert result["count"] >= 1
    assert all(p["status"] == "active" for p in result["plans"])


# ── scenario_tool ─────────────────────────────────────────────────────────────
async def test_generate_rest_api(store, plan):
    result = await generate_scenarios(store, plan_id=plan["id"], category="rest_api")
    assert result["generated_count"] > 0
    assert result["category"] == "rest_api"
    assert len(result["scenarios"]) == result["generated_count"]


async def test_generate_invalid_category(store, plan):
    res = await generate_scenarios(store, plan_id=plan["id"], category="invalida")
    assert res["error"] == "ValidationError"


async def test_generate_missing_plan_id(store):
    assert (await generate_scenarios(store, plan_id="", category="rest_api"))["error"] == "ValidationError"


async def test_generate_plan_not_found(store):
    assert (await generate_scenarios(store, plan_id="999999", category="rest_api"))["error"] == "not_found"


async def test_generate_with_context_replaces_endpoint(store, plan):
    result = await generate_scenarios(store, plan_id=plan["id"], category="rest_api", context="/api/users")
    assert result["generated_count"] > 0
    steps = [s["steps"] for s in await store.get_scenarios(plan["id"])]
    assert any("/api/users" in st for st in steps)
    assert all("{endpoint}" not in st for st in steps)


async def test_add_scenario_ok(store, plan):
    result = await add_scenario(
        store,
        plan_id=plan["id"],
        name="Cenário custom",
        category="happy_path",
        steps="Executar GET /api/test",
        expected_result="Status 200",
        priority="high",
    )
    assert result["scenario_id"] is not None
    assert result["name"] == "Cenário custom"


async def test_add_scenario_invalid_category(store, plan):
    result = await add_scenario(
        store, plan_id=plan["id"], name="X", category="invalida", steps="s", expected_result="r"
    )
    assert result["error"] == "ValidationError"


async def test_add_scenario_missing_required(store, plan):
    result = await add_scenario(
        store, plan_id=plan["id"], name="", category="happy_path", steps="", expected_result=""
    )
    assert result["error"] == "ValidationError"


async def test_add_scenario_invalid_priority(store, plan):
    result = await add_scenario(
        store,
        plan_id=plan["id"],
        name="X",
        category="happy_path",
        steps="s",
        expected_result="r",
        priority="urgentissimo",
    )
    assert result["error"] == "ValidationError"


async def test_add_scenario_plan_not_found(store):
    result = await add_scenario(
        store, plan_id="999999", name="X", category="happy_path", steps="s", expected_result="r"
    )
    assert result["error"] == "not_found"


async def test_record_result_ok(store, plan):
    scenario = await add_scenario(
        store, plan_id=plan["id"], name="S", category="happy_path", steps="s", expected_result="r"
    )
    result = await record_result(
        store,
        plan_id=plan["id"],
        scenario_id=scenario["scenario_id"],
        status="passed",
        actual_result="200 OK",
    )
    assert result["status"] == "passed"
    assert result["result_id"] is not None


async def test_record_result_invalid_status(store, plan):
    res = await record_result(store, plan_id=plan["id"], scenario_id=1, status="unknown")
    assert res["error"] == "ValidationError"


async def test_record_result_missing_fields(store):
    res = await record_result(store, plan_id="", scenario_id=0, status="passed")
    assert res["error"] == "ValidationError"


async def test_record_result_plan_not_found(store):
    res = await record_result(store, plan_id="999999", scenario_id=1, status="passed")
    assert res["error"] == "not_found"


# ── checklist_tool ────────────────────────────────────────────────────────────
async def test_create_checklist_from_template(store):
    result = await create_checklist(store, title="Pré-deploy", checklist_type="pre_deploy")
    assert result["items_count"] > 0
    assert result["type"] == "pre_deploy"
    assert "checklist_id" in result
    assert "run_checklist" in result["hint"]


async def test_create_checklist_missing_title(store):
    assert (await create_checklist(store, title="", checklist_type="pre_deploy"))[
        "error"
    ] == "ValidationError"


async def test_create_checklist_invalid_type(store):
    assert (await create_checklist(store, title="X", checklist_type="inexistente"))[
        "error"
    ] == "ValidationError"


async def test_create_checklist_custom_items(store):
    items = [
        {"description": "Item A", "required": True, "category": "quality"},
        {"description": "Item B", "required": False},
    ]
    result = await create_checklist(
        store, title="Custom", checklist_type="custom", items=items, use_template=False
    )
    assert result["items_count"] == 2


async def test_create_checklist_custom_without_items(store):
    result = await create_checklist(store, title="Custom", checklist_type="custom", use_template=False)
    assert result["error"] == "ValidationError"


async def test_create_checklist_item_missing_description(store):
    result = await create_checklist(
        store, title="Bad", checklist_type="custom", items=[{"category": "quality"}], use_template=False
    )
    assert result["error"] == "ValidationError"


async def test_create_checklist_invalid_plan(store):
    result = await create_checklist(store, title="X", checklist_type="pre_deploy", plan_id="999999")
    assert result["error"] == "not_found"


async def test_create_checklist_with_valid_plan(store, plan):
    result = await create_checklist(
        store, title="Ligado ao plano", checklist_type="security", plan_id=plan["id"]
    )
    assert result["items_count"] > 0


async def test_run_checklist_and_check_items_completes(store):
    created = await create_checklist(store, title="Pré-deploy", checklist_type="pre_deploy")
    run = await run_checklist(store, checklist_id=created["checklist_id"], executor="qa")
    assert run["run_id"].startswith("run_")
    assert len(run["items"]) == created["items_count"]

    for item in run["items"]:
        res = await check_item(store, run_id=run["run_id"], item_id=item["id"], status="passed")
        assert res["item_id"] == item["id"]

    status = await get_run_status(store, run_id=run["run_id"])
    assert status["status"] == "completed"
    assert status["summary"]["passed"] == created["items_count"]
    assert status["summary"]["pending"] == 0


async def test_run_checklist_missing_id(store):
    assert (await run_checklist(store, checklist_id=""))["error"] == "ValidationError"


async def test_run_checklist_unknown_checklist(store):
    # store.start_run devolve run mesmo sem itens; a tool só falha se o store devolver None.
    result = await run_checklist(store, checklist_id="9999")
    assert result["run_id"].startswith("run_")
    assert result["items"] == []


async def test_check_item_validation_errors(store):
    created = await create_checklist(store, title="X", checklist_type="pre_deploy")
    run = await run_checklist(store, checklist_id=created["checklist_id"])
    item_id = run["items"][0]["id"]
    bad_status = await check_item(store, run_id=run["run_id"], item_id=item_id, status="talvez")
    assert bad_status["error"] == "ValidationError"
    assert (await check_item(store, run_id="", item_id=item_id, status="passed"))[
        "error"
    ] == "ValidationError"


async def test_check_item_unknown_run(store):
    result = await check_item(store, run_id="run_naoexiste", item_id=1, status="passed")
    assert result["run_id"] == "run_naoexiste"
    assert result["status"] == "passed"


async def test_get_run_status_missing_id(store):
    assert (await get_run_status(store, run_id=""))["error"] == "ValidationError"


async def test_get_run_status_not_found(store):
    assert (await get_run_status(store, run_id="run_inexistente"))["error"] == "not_found"


async def test_partial_check_keeps_run_in_progress(store):
    created = await create_checklist(store, title="X", checklist_type="pre_deploy")
    run = await run_checklist(store, checklist_id=created["checklist_id"])
    first = run["items"][0]
    res = await check_item(store, run_id=run["run_id"], item_id=first["id"], status="passed")
    assert res["run_status"] == "in_progress"


# ── validation_tool ───────────────────────────────────────────────────────────
async def test_add_finding_ok(store, plan):
    result = await add_finding(
        store,
        plan_id=plan["id"],
        severity="high",
        title="Endpoint retorna 500",
        description="Quando banco está indisponível, retorna stack trace",
    )
    assert result["finding_id"] is not None
    assert result["severity"] == "high"


async def test_add_finding_critical_has_warning(store, plan):
    result = await add_finding(
        store,
        plan_id=plan["id"],
        severity="critical",
        title="SQL Injection",
        description="Campo X é vulnerável",
    )
    assert "warning" in result


async def test_add_finding_invalid_severity(store, plan):
    res = await add_finding(store, plan_id=plan["id"], severity="ultra", title="X", description="Y")
    assert res["error"] == "ValidationError"


async def test_add_finding_missing_fields(store, plan):
    res = await add_finding(store, plan_id=plan["id"], severity="high", title="", description="")
    assert res["error"] == "ValidationError"


async def test_add_finding_plan_not_found(store):
    res = await add_finding(store, plan_id="999999", severity="high", title="T", description="D")
    assert res["error"] == "not_found"


async def test_double_check_empty_plan_blocked(store, plan):
    await generate_scenarios(store, plan_id=plan["id"], category="rest_api")
    result = await double_check(store, plan_id=plan["id"])
    assert result["summary"]["ready_to_ship"] is False
    assert "BLOQUEADO" in result["verdict"]


async def test_double_check_all_passed(store, plan):
    sc = await add_scenario(
        store, plan_id=plan["id"], name="S", category="happy_path", steps="s", expected_result="r"
    )
    await record_result(store, plan_id=plan["id"], scenario_id=sc["scenario_id"], status="passed")
    result = await double_check(store, plan_id=plan["id"])
    assert result["summary"]["ready_to_ship"] is True
    assert "APROVADO" in result["verdict"]


async def test_double_check_missing_plan_id(store):
    assert (await double_check(store, plan_id=""))["error"] == "ValidationError"


async def test_double_check_plan_not_found(store):
    assert (await double_check(store, plan_id="999999"))["error"] == "not_found"


async def test_get_validation_status(store, plan):
    sc = await add_scenario(
        store, plan_id=plan["id"], name="S", category="happy_path", steps="s", expected_result="r"
    )
    await record_result(store, plan_id=plan["id"], scenario_id=sc["scenario_id"], status="passed")
    result = await get_validation_status(store, plan_id=plan["id"])
    assert "grade" in result
    assert "coverage_pct" in result
    assert "pass_rate" in result
    assert "grade_description" in result


async def test_get_validation_status_missing_plan_id(store):
    assert (await get_validation_status(store, plan_id=""))["error"] == "ValidationError"


async def test_get_validation_status_plan_not_found(store):
    assert (await get_validation_status(store, plan_id="999999"))["error"] == "not_found"


async def test_get_validation_status_ship_blockers_low_coverage(store, plan):
    await generate_scenarios(store, plan_id=plan["id"], category="rest_api")
    result = await get_validation_status(store, plan_id=plan["id"])
    assert result["ready_to_ship"] is False
    assert any("Cobertura" in b for b in result["ship_blockers"])
    assert any("Pass rate" in b for b in result["ship_blockers"])


async def test_get_validation_status_critical_finding_blocker(store, plan):
    sc = await add_scenario(
        store, plan_id=plan["id"], name="S", category="happy_path", steps="s", expected_result="r"
    )
    await record_result(store, plan_id=plan["id"], scenario_id=sc["scenario_id"], status="passed")
    await add_finding(store, plan_id=plan["id"], severity="critical", title="C", description="D")
    result = await get_validation_status(store, plan_id=plan["id"])
    assert result["grade"] == "F"
    assert result["ready_to_ship"] is False
    assert any("critico" in b for b in result["ship_blockers"])
