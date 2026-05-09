"""Testes para validation_tool e double_check."""

from src.tools.scenario_tool import add_scenario, generate_scenarios, record_result
from src.tools.validation_tool import add_finding, double_check, get_validation_status


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
    result = add_finding(store, plan_id=plan["id"], severity="ultra", title="X", description="Y")
    assert result["error"] == "ValidationError"


def test_double_check_empty_plan_blocked(store, plan):
    # Plan with no scenarios → not ready
    # Generate some scenarios but don't record results
    generate_scenarios(store, plan_id=plan["id"], category="rest_api")
    result = double_check(store, plan_id=plan["id"])
    assert result["summary"]["ready_to_ship"] is False
    assert "BLOQUEADO" in result["verdict"]


def test_double_check_all_passed(store, plan):
    sc = add_scenario(
        store,
        plan_id=plan["id"],
        name="S",
        category="happy_path",
        steps="s",
        expected_result="r",
    )
    record_result(store, plan_id=plan["id"], scenario_id=sc["scenario_id"], status="passed")
    result = double_check(store, plan_id=plan["id"])
    assert result["summary"]["ready_to_ship"] is True
    assert "APROVADO" in result["verdict"]


def test_double_check_critical_finding_blocks(store, plan):
    sc = add_scenario(
        store,
        plan_id=plan["id"],
        name="S",
        category="happy_path",
        steps="s",
        expected_result="r",
    )
    record_result(store, plan_id=plan["id"], scenario_id=sc["scenario_id"], status="passed")
    add_finding(store, plan_id=plan["id"], severity="critical", title="Bug crítico", description="X")
    result = double_check(store, plan_id=plan["id"])
    assert result["summary"]["ready_to_ship"] is False


def test_get_validation_status(store, plan):
    sc = add_scenario(
        store,
        plan_id=plan["id"],
        name="S",
        category="happy_path",
        steps="s",
        expected_result="r",
    )
    record_result(store, plan_id=plan["id"], scenario_id=sc["scenario_id"], status="passed")
    result = get_validation_status(store, plan_id=plan["id"])
    assert "grade" in result
    assert "coverage_pct" in result
    assert "pass_rate" in result
    assert "grade_description" in result
