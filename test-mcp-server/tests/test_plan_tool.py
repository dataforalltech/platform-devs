"""Testes para plan_tool."""

from src.tools.plan_tool import create_test_plan, get_test_plan, list_test_plans


def test_create_plan_ok(store):
    result = create_test_plan(store, title="Meu Plano", scope="Feature X")
    assert result["title"] == "Meu Plano"
    assert result["status"] == "active"
    assert result["id"].startswith("plan_")


def test_create_plan_missing_fields(store):
    result = create_test_plan(store, title="", scope="X")
    assert result["error"] == "ValidationError"


def test_get_plan_ok(store, plan):
    result = get_test_plan(store, plan_id=plan["id"])
    assert result["id"] == plan["id"]
    assert "coverage" in result


def test_get_plan_not_found(store):
    result = get_test_plan(store, plan_id="plan_naoexiste")
    assert result["error"] == "not_found"


def test_list_plans(store):
    create_test_plan(store, title="A", scope="s1")
    create_test_plan(store, title="B", scope="s2")
    result = list_test_plans(store)
    assert result["count"] >= 2


def test_list_plans_invalid_status(store):
    result = list_test_plans(store, status="invalido")
    assert result["error"] == "ValidationError"
