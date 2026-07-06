"""Testes de baixo nível do TestStore (camada psycopg2 trocada por SQLite).

Cobrem helpers, o rewrite do LEFT JOIN LATERAL de get_scenarios, o caminho de
rollback do context manager _get_conn e o close() do pool.
"""

import pytest

# importado sob alias para o pytest não tentar coletar a classe (nome Test*).
from src.db.store import TestStore as Store


def test_to_int_id_valid_and_invalid():
    assert Store._to_int_id("42") == 42
    assert Store._to_int_id(7) == 7
    with pytest.raises(ValueError):
        Store._to_int_id("nao_numerico")


def test_grade_boundaries():
    # crítico em aberto -> F imediato
    assert Store._grade(100.0, 100.0, {"critical": 1}) == "F"
    assert Store._grade(100.0, 100.0, {}) == "A"
    assert Store._grade(80.0, 80.0, {}) == "B"
    assert Store._grade(70.0, 70.0, {}) == "C"
    assert Store._grade(60.0, 60.0, {}) == "D"
    assert Store._grade(10.0, 10.0, {}) == "F"


def test_get_scenarios_last_status_reflects_recorded_result(store, plan):
    sc = store.add_scenario(
        plan_id=plan["id"],
        name="S",
        category="happy_path",
        steps="s",
        expected_result="r",
    )
    sid = sc["scenario_id"]
    store.record_result(plan_id=plan["id"], scenario_id=sid, status="passed")

    scenarios = store.get_scenarios(plan["id"])
    assert len(scenarios) == 1
    # o rewrite do LEFT JOIN LATERAL deve trazer o status executado do cenário.
    assert scenarios[0]["last_status"] == "passed"


def test_get_scenarios_without_results_is_null(store, plan):
    store.add_scenario(
        plan_id=plan["id"],
        name="S",
        category="happy_path",
        steps="s",
        expected_result="r",
    )
    scenarios = store.get_scenarios(plan["id"])
    assert scenarios[0]["last_status"] is None


def test_get_plan_counts_and_coverage(store, plan):
    sc = store.add_scenario(
        plan_id=plan["id"], name="S", category="happy_path", steps="s", expected_result="r"
    )
    store.record_result(plan_id=plan["id"], scenario_id=sc["scenario_id"], status="passed")
    store.add_finding(plan_id=plan["id"], severity="low", title="t", description="d")
    full = store.get_plan(plan["id"])
    assert full["scenarios_count"] == 1
    assert full["results_count"] == 1
    assert full["findings_count"] == 1
    assert full["coverage"]["passed"] == 1


def test_get_conn_rollback_on_error(store, monkeypatch):
    """Uma exceção dentro do bloco with deve disparar rollback e propagar."""
    calls = {"rollback": 0}
    with store._get_conn() as conn:
        original_rollback = conn.rollback

        def _spy():
            calls["rollback"] += 1
            return original_rollback()

        monkeypatch.setattr(conn, "rollback", _spy)

    with pytest.raises(RuntimeError):
        with store._get_conn() as conn:
            raise RuntimeError("boom")
    assert calls["rollback"] == 1


def test_close_pool(store):
    # não deve levantar; fecha a conexão SQLite subjacente do pool fake.
    store.close()


def test_double_check_ready_when_all_passed(store, plan):
    sc = store.add_scenario(
        plan_id=plan["id"], name="S", category="happy_path", steps="s", expected_result="r"
    )
    store.record_result(plan_id=plan["id"], scenario_id=sc["scenario_id"], status="passed")
    result = store.double_check(plan["id"])
    assert result["summary"]["ready_to_ship"] is True
    assert result["summary"]["total_scenarios"] == 1
