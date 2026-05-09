"""Testes para scenario_tool."""

from src.tools.scenario_tool import add_scenario, generate_scenarios, record_result


def test_generate_rest_api(store, plan):
    result = generate_scenarios(store, plan_id=plan["id"], category="rest_api")
    assert result["generated_count"] > 0
    assert result["category"] == "rest_api"
    assert len(result["scenarios"]) == result["generated_count"]


def test_generate_with_context(store, plan):
    result = generate_scenarios(store, plan_id=plan["id"], category="rest_api", context="/api/users")
    # Context should replace {endpoint} in scenario names/steps
    assert result["generated_count"] > 0


def test_generate_invalid_category(store, plan):
    result = generate_scenarios(store, plan_id=plan["id"], category="invalida")
    assert result["error"] == "ValidationError"


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
        store,
        plan_id=plan["id"],
        name="X",
        category="invalida",
        steps="s",
        expected_result="r",
    )
    assert result["error"] == "ValidationError"


def test_record_result_ok(store, plan):
    scenario = add_scenario(
        store,
        plan_id=plan["id"],
        name="S",
        category="happy_path",
        steps="s",
        expected_result="r",
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
    result = record_result(store, plan_id=plan["id"], scenario_id=1, status="unknown")
    assert result["error"] == "ValidationError"
