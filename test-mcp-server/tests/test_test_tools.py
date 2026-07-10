"""Testes das tools reais do test-mcp (plan/scenario/checklist/validation).

Exercitam a lógica de negócio preservada em src/tools/ — saída DERIVADA dos
inputs — com o ``store`` real cuja camada psycopg2 foi trocada por SQLite
in-memory (ver conftest). Nenhum I/O de rede/DB real.
"""

from __future__ import annotations

from src.tools.checklist_tool import (
    check_item,
    create_checklist,
    get_run_status,
    run_checklist,
)
from src.tools.plan_tool import create_test_plan, get_test_plan, list_test_plans
from src.tools.scenario_tool import add_scenario, generate_scenarios, record_result
from src.tools.validation_tool import add_finding, double_check, get_validation_status

# ── plan_tool ─────────────────────────────────────────────────────────────────


def test_create_plan_ok(store):
    result = create_test_plan(store, title="Meu Plano", scope="Feature X")
    assert result["title"] == "Meu Plano"
    assert result["status"] == "active"
    assert isinstance(result["id"], int)
    assert result["id"] > 0


def test_create_plan_missing_fields(store):
    result = create_test_plan(store, title="", scope="X")
    assert result["error"] == "ValidationError"


def test_get_plan_ok(store, plan):
    result = get_test_plan(store, plan_id=plan["id"])
    assert result["id"] == plan["id"]
    assert "coverage" in result


def test_get_plan_not_found(store):
    result = get_test_plan(store, plan_id="999999")
    assert result["error"] == "not_found"


def test_get_plan_missing_id(store):
    assert get_test_plan(store, plan_id="")["error"] == "ValidationError"


def test_get_plan_include_scenarios(store, plan):
    result = get_test_plan(store, plan_id=plan["id"], include_scenarios=True)
    assert isinstance(result["scenarios"], list)


def test_list_plans(store):
    create_test_plan(store, title="A", scope="s1")
    create_test_plan(store, title="B", scope="s2")
    assert list_test_plans(store)["count"] >= 2


def test_list_plans_invalid_status(store):
    assert list_test_plans(store, status="invalido")["error"] == "ValidationError"


def test_list_plans_filtered_by_status(store):
    create_test_plan(store, title="A", scope="s1")
    result = list_test_plans(store, status="active")
    assert result["count"] >= 1
    assert all(p["status"] == "active" for p in result["plans"])


# ── scenario_tool ─────────────────────────────────────────────────────────────


def test_generate_rest_api(store, plan):
    result = generate_scenarios(store, plan_id=plan["id"], category="rest_api")
    assert result["generated_count"] > 0
    assert result["category"] == "rest_api"
    assert len(result["scenarios"]) == result["generated_count"]


def test_generate_invalid_category(store, plan):
    assert generate_scenarios(store, plan_id=plan["id"], category="invalida")["error"] == "ValidationError"


def test_generate_missing_plan_id(store):
    assert generate_scenarios(store, plan_id="", category="rest_api")["error"] == "ValidationError"


def test_generate_plan_not_found(store):
    assert generate_scenarios(store, plan_id="999999", category="rest_api")["error"] == "not_found"


def test_generate_with_context_replaces_endpoint(store, plan):
    result = generate_scenarios(store, plan_id=plan["id"], category="rest_api", context="/api/users")
    assert result["generated_count"] > 0
    steps = [s["steps"] for s in store.get_scenarios(plan["id"])]
    assert any("/api/users" in st for st in steps)
    assert all("{endpoint}" not in st for st in steps)


def test_add_scenario_ok(store, plan):
    result = add_scenario(
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


def test_add_scenario_invalid_category(store, plan):
    result = add_scenario(
        store, plan_id=plan["id"], name="X", category="invalida", steps="s", expected_result="r"
    )
    assert result["error"] == "ValidationError"


def test_add_scenario_missing_required(store, plan):
    result = add_scenario(
        store, plan_id=plan["id"], name="", category="happy_path", steps="", expected_result=""
    )
    assert result["error"] == "ValidationError"


def test_add_scenario_invalid_priority(store, plan):
    result = add_scenario(
        store,
        plan_id=plan["id"],
        name="X",
        category="happy_path",
        steps="s",
        expected_result="r",
        priority="urgentissimo",
    )
    assert result["error"] == "ValidationError"


def test_add_scenario_plan_not_found(store):
    result = add_scenario(
        store, plan_id="999999", name="X", category="happy_path", steps="s", expected_result="r"
    )
    assert result["error"] == "not_found"


def test_record_result_ok(store, plan):
    scenario = add_scenario(
        store, plan_id=plan["id"], name="S", category="happy_path", steps="s", expected_result="r"
    )
    result = record_result(
        store,
        plan_id=plan["id"],
        scenario_id=scenario["scenario_id"],
        status="passed",
        actual_result="200 OK",
    )
    assert result["status"] == "passed"
    assert result["result_id"] is not None


def test_record_result_invalid_status(store, plan):
    assert (
        record_result(store, plan_id=plan["id"], scenario_id=1, status="unknown")["error"]
        == "ValidationError"
    )


def test_record_result_missing_fields(store):
    assert record_result(store, plan_id="", scenario_id=0, status="passed")["error"] == "ValidationError"


def test_record_result_plan_not_found(store):
    assert record_result(store, plan_id="999999", scenario_id=1, status="passed")["error"] == "not_found"


# ── checklist_tool ────────────────────────────────────────────────────────────


def test_create_checklist_from_template(store):
    result = create_checklist(store, title="Pré-deploy", checklist_type="pre_deploy")
    assert result["items_count"] > 0
    assert result["type"] == "pre_deploy"
    assert "checklist_id" in result
    assert "run_checklist" in result["hint"]


def test_create_checklist_missing_title(store):
    assert create_checklist(store, title="", checklist_type="pre_deploy")["error"] == "ValidationError"


def test_create_checklist_invalid_type(store):
    assert create_checklist(store, title="X", checklist_type="inexistente")["error"] == "ValidationError"


def test_create_checklist_custom_items(store):
    items = [
        {"description": "Item A", "required": True, "category": "quality"},
        {"description": "Item B", "required": False},
    ]
    result = create_checklist(store, title="Custom", checklist_type="custom", items=items, use_template=False)
    assert result["items_count"] == 2


def test_create_checklist_custom_without_items(store):
    result = create_checklist(store, title="Custom", checklist_type="custom", use_template=False)
    assert result["error"] == "ValidationError"


def test_create_checklist_item_missing_description(store):
    result = create_checklist(
        store, title="Bad", checklist_type="custom", items=[{"category": "quality"}], use_template=False
    )
    assert result["error"] == "ValidationError"


def test_create_checklist_invalid_plan(store):
    assert (
        create_checklist(store, title="X", checklist_type="pre_deploy", plan_id="999999")["error"]
        == "not_found"
    )


def test_create_checklist_with_valid_plan(store, plan):
    result = create_checklist(store, title="Ligado ao plano", checklist_type="security", plan_id=plan["id"])
    assert result["items_count"] > 0


def test_run_checklist_and_check_items_completes(store):
    created = create_checklist(store, title="Pré-deploy", checklist_type="pre_deploy")
    run = run_checklist(store, checklist_id=created["checklist_id"], executor="qa")
    assert run["run_id"].startswith("run_")
    assert len(run["items"]) == created["items_count"]

    for item in run["items"]:
        res = check_item(store, run_id=run["run_id"], item_id=item["id"], status="passed")
        assert res["item_id"] == item["id"]

    status = get_run_status(store, run_id=run["run_id"])
    assert status["status"] == "completed"
    assert status["summary"]["passed"] == created["items_count"]
    assert status["summary"]["pending"] == 0


def test_run_checklist_missing_id(store):
    assert run_checklist(store, checklist_id="")["error"] == "ValidationError"


def test_run_checklist_unknown_checklist(store):
    # store.start_run devolve run mesmo sem itens; a tool só falha se o store devolver None.
    result = run_checklist(store, checklist_id="9999")
    assert result["run_id"].startswith("run_")
    assert result["items"] == []


def test_check_item_validation_errors(store):
    created = create_checklist(store, title="X", checklist_type="pre_deploy")
    run = run_checklist(store, checklist_id=created["checklist_id"])
    item_id = run["items"][0]["id"]
    assert (
        check_item(store, run_id=run["run_id"], item_id=item_id, status="talvez")["error"]
        == "ValidationError"
    )
    assert check_item(store, run_id="", item_id=item_id, status="passed")["error"] == "ValidationError"


def test_check_item_unknown_run(store):
    result = check_item(store, run_id="run_naoexiste", item_id=1, status="passed")
    assert result["run_id"] == "run_naoexiste"
    assert result["status"] == "passed"


def test_get_run_status_missing_id(store):
    assert get_run_status(store, run_id="")["error"] == "ValidationError"


def test_get_run_status_not_found(store):
    assert get_run_status(store, run_id="run_inexistente")["error"] == "not_found"


def test_partial_check_keeps_run_in_progress(store):
    created = create_checklist(store, title="X", checklist_type="pre_deploy")
    run = run_checklist(store, checklist_id=created["checklist_id"])
    first = run["items"][0]
    res = check_item(store, run_id=run["run_id"], item_id=first["id"], status="passed")
    assert res["run_status"] == "in_progress"


# ── validation_tool ───────────────────────────────────────────────────────────


def test_add_finding_ok(store, plan):
    result = add_finding(
        store,
        plan_id=plan["id"],
        severity="high",
        title="Endpoint retorna 500",
        description="Quando banco está indisponível, retorna stack trace",
    )
    assert result["finding_id"] is not None
    assert result["severity"] == "high"


def test_add_finding_critical_has_warning(store, plan):
    result = add_finding(
        store,
        plan_id=plan["id"],
        severity="critical",
        title="SQL Injection",
        description="Campo X é vulnerável",
    )
    assert "warning" in result


def test_add_finding_invalid_severity(store, plan):
    assert (
        add_finding(store, plan_id=plan["id"], severity="ultra", title="X", description="Y")["error"]
        == "ValidationError"
    )


def test_add_finding_missing_fields(store, plan):
    assert (
        add_finding(store, plan_id=plan["id"], severity="high", title="", description="")["error"]
        == "ValidationError"
    )


def test_add_finding_plan_not_found(store):
    assert (
        add_finding(store, plan_id="999999", severity="high", title="T", description="D")["error"]
        == "not_found"
    )


def test_double_check_empty_plan_blocked(store, plan):
    generate_scenarios(store, plan_id=plan["id"], category="rest_api")
    result = double_check(store, plan_id=plan["id"])
    assert result["summary"]["ready_to_ship"] is False
    assert "BLOQUEADO" in result["verdict"]


def test_double_check_all_passed(store, plan):
    sc = add_scenario(
        store, plan_id=plan["id"], name="S", category="happy_path", steps="s", expected_result="r"
    )
    record_result(store, plan_id=plan["id"], scenario_id=sc["scenario_id"], status="passed")
    result = double_check(store, plan_id=plan["id"])
    assert result["summary"]["ready_to_ship"] is True
    assert "APROVADO" in result["verdict"]


def test_double_check_critical_finding_blocks(store, plan):
    sc = add_scenario(
        store, plan_id=plan["id"], name="S", category="happy_path", steps="s", expected_result="r"
    )
    record_result(store, plan_id=plan["id"], scenario_id=sc["scenario_id"], status="passed")
    add_finding(store, plan_id=plan["id"], severity="critical", title="Bug crítico", description="X")
    assert double_check(store, plan_id=plan["id"])["summary"]["ready_to_ship"] is False


def test_double_check_missing_plan_id(store):
    assert double_check(store, plan_id="")["error"] == "ValidationError"


def test_double_check_plan_not_found(store):
    assert double_check(store, plan_id="999999")["error"] == "not_found"


def test_double_check_reports_failed_and_not_executed_blockers(store, plan):
    passed = add_scenario(
        store, plan_id=plan["id"], name="ok", category="happy_path", steps="s", expected_result="r"
    )
    record_result(store, plan_id=plan["id"], scenario_id=passed["scenario_id"], status="passed")
    failing = add_scenario(
        store, plan_id=plan["id"], name="ko", category="error", steps="s", expected_result="r"
    )
    record_result(store, plan_id=plan["id"], scenario_id=failing["scenario_id"], status="failed")
    add_scenario(store, plan_id=plan["id"], name="np", category="boundary", steps="s", expected_result="r")
    result = double_check(store, plan_id=plan["id"])
    assert result["summary"]["ready_to_ship"] is False
    assert "falha" in result["verdict"]
    assert "nao executado" in result["verdict"]


def test_get_validation_status(store, plan):
    sc = add_scenario(
        store, plan_id=plan["id"], name="S", category="happy_path", steps="s", expected_result="r"
    )
    record_result(store, plan_id=plan["id"], scenario_id=sc["scenario_id"], status="passed")
    result = get_validation_status(store, plan_id=plan["id"])
    assert "grade" in result
    assert "coverage_pct" in result
    assert "pass_rate" in result
    assert "grade_description" in result


def test_get_validation_status_missing_plan_id(store):
    assert get_validation_status(store, plan_id="")["error"] == "ValidationError"


def test_get_validation_status_plan_not_found(store):
    assert get_validation_status(store, plan_id="999999")["error"] == "not_found"


def test_get_validation_status_ship_blockers_low_coverage(store, plan):
    generate_scenarios(store, plan_id=plan["id"], category="rest_api")
    result = get_validation_status(store, plan_id=plan["id"])
    assert result["ready_to_ship"] is False
    assert any("Cobertura" in b for b in result["ship_blockers"])
    assert any("Pass rate" in b for b in result["ship_blockers"])


def test_get_validation_status_critical_finding_blocker(store, plan):
    sc = add_scenario(
        store, plan_id=plan["id"], name="S", category="happy_path", steps="s", expected_result="r"
    )
    record_result(store, plan_id=plan["id"], scenario_id=sc["scenario_id"], status="passed")
    add_finding(store, plan_id=plan["id"], severity="critical", title="C", description="D")
    result = get_validation_status(store, plan_id=plan["id"])
    assert result["grade"] == "F"
    assert result["ready_to_ship"] is False
    assert any("critico" in b for b in result["ship_blockers"])
