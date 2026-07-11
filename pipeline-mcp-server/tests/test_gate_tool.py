"""Gate tools (async) contra store MySQL real."""

from __future__ import annotations

import pytest

from src.tools import add_gate_result, clear_gates, get_gate_status

from .conftest import requires_mysql

pytestmark = [pytest.mark.integration, requires_mysql]


async def test_add_gate_invalid_type(store_a):
    await store_a.register_pipeline("svc", "o/svc")
    r = await add_gate_result(store_a, "svc", "dev", "bogus", True)
    assert r["error"] == "invalid_gate_type"
    assert "qa_tests" in r["valid_types"]


async def test_add_gate_service_not_found(store_a):
    r = await add_gate_result(store_a, "nope", "dev", "qa_tests", True)
    assert r["error"] == "not_found"


async def test_add_and_status(store_a):
    await store_a.register_pipeline("svc", "o/svc")
    await store_a.set_gates_config("svc", {"homol": ["qa_tests", "pr_approved"]})
    rec = await add_gate_result(store_a, "svc", "homol", "qa_tests", True, details="ok", evaluated_by="ci")
    assert rec["gate_recorded"] is True

    status = await get_gate_status(store_a, "svc", "homol")
    assert status["can_promote"] is False  # pr_approved ausente
    assert "pr_approved" in status["missing_gates"]

    # gate registrado mas não exigido aparece como "extra"
    await add_gate_result(store_a, "svc", "homol", "security_scan", True)
    status2 = await get_gate_status(store_a, "svc", "homol")
    assert any(g["status"] == "extra" for g in status2["gates"])


async def test_status_all_pass(store_a):
    await store_a.register_pipeline("svc", "o/svc")
    await store_a.set_gates_config("svc", {"homol": ["qa_tests"]})
    await add_gate_result(store_a, "svc", "homol", "qa_tests", True)
    status = await get_gate_status(store_a, "svc", "homol")
    assert status["can_promote"] is True


async def test_get_gate_status_not_found(store_a):
    assert (await get_gate_status(store_a, "nope", "dev"))["error"] == "not_found"


async def test_clear_gates(store_a):
    await store_a.register_pipeline("svc", "o/svc")
    await add_gate_result(store_a, "svc", "dev", "qa_tests", True)
    r = await clear_gates(store_a, "svc", "dev")
    assert r["cleared"] is True and r["deleted_count"] == 1
    assert (await clear_gates(store_a, "nope", "dev"))["error"] == "not_found"
