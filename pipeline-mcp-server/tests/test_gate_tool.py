"""Testes das tools de gate (src/tools/gate_tool.py)."""

from __future__ import annotations

from src.tools.gate_tool import add_gate_result, clear_gates, get_gate_status


class TestAddGateResult:
    def test_invalid_gate_type(self, registered_store):
        result = add_gate_result(
            registered_store, service="svc-a", env="dev", gate_type="bogus", passed=True
        )
        assert result["error"] == "invalid_gate_type"
        assert "qa_tests" in result["valid_types"]

    def test_service_not_found(self, store):
        result = add_gate_result(
            store, service="ghost", env="dev", gate_type="qa_tests", passed=True
        )
        assert result == {"error": "not_found", "service": "ghost"}

    def test_records_gate(self, registered_store):
        result = add_gate_result(
            registered_store,
            service="svc-a",
            env="dev",
            gate_type="qa_tests",
            passed=True,
            details="coverage 92%",
            evaluated_by="ci",
        )
        assert result["gate_recorded"] is True
        assert result["gate"]["gate_type"] == "qa_tests"
        assert result["gate"]["passed"] == 1

    def test_upsert_overwrites(self, registered_store):
        add_gate_result(registered_store, "svc-a", "dev", "qa_tests", True)
        add_gate_result(registered_store, "svc-a", "dev", "qa_tests", False, details="regressed")
        gates = registered_store.get_gates("svc-a", "dev")
        assert len(gates) == 1
        assert gates[0]["passed"] == 0
        assert gates[0]["details"] == "regressed"


class TestGetGateStatus:
    def test_service_not_found(self, store):
        assert get_gate_status(store, "ghost", "homol") == {
            "error": "not_found",
            "service": "ghost",
        }

    def test_all_required_missing(self, registered_store):
        # homol default requer qa_tests, pr_approved, audit_compliance — nenhum registrado
        result = get_gate_status(registered_store, "svc-a", "homol")
        assert result["can_promote"] is False
        assert set(result["missing_gates"]) == {"qa_tests", "pr_approved", "audit_compliance"}
        assert all(g["status"] == "missing" for g in result["gates"])

    def test_can_promote_when_all_pass(self, registered_store):
        for gate in ("qa_tests", "pr_approved", "audit_compliance"):
            registered_store.upsert_gate("svc-a", "homol", gate, True)
        result = get_gate_status(registered_store, "svc-a", "homol")
        assert result["can_promote"] is True
        assert result["missing_gates"] == []
        assert all(g["status"] == "passed" for g in result["gates"])

    def test_failed_gate_blocks(self, registered_store):
        registered_store.upsert_gate("svc-a", "homol", "qa_tests", True)
        registered_store.upsert_gate("svc-a", "homol", "pr_approved", False)
        registered_store.upsert_gate("svc-a", "homol", "audit_compliance", True)
        result = get_gate_status(registered_store, "svc-a", "homol")
        assert result["can_promote"] is False
        statuses = {g["gate_type"]: g["status"] for g in result["gates"]}
        assert statuses["pr_approved"] == "failed"
        assert statuses["qa_tests"] == "passed"

    def test_extra_gates_listed(self, registered_store):
        # dev default só exige audit_compliance; um gate extra (health_check) aparece como 'extra'
        registered_store.upsert_gate("svc-a", "dev", "audit_compliance", True)
        registered_store.upsert_gate("svc-a", "dev", "health_check", True)
        result = get_gate_status(registered_store, "svc-a", "dev")
        statuses = {g["gate_type"]: g["status"] for g in result["gates"]}
        assert statuses["audit_compliance"] == "passed"
        assert statuses["health_check"] == "extra"
        # gate extra não afeta can_promote
        assert result["can_promote"] is True


class TestClearGates:
    def test_service_not_found(self, store):
        assert clear_gates(store, "ghost", "dev") == {"error": "not_found", "service": "ghost"}

    def test_clears_only_target_env(self, registered_store):
        registered_store.upsert_gate("svc-a", "dev", "qa_tests", True)
        registered_store.upsert_gate("svc-a", "dev", "pr_approved", True)
        registered_store.upsert_gate("svc-a", "homol", "qa_tests", True)
        result = clear_gates(registered_store, "svc-a", "dev")
        assert result["cleared"] is True
        assert result["deleted_count"] == 2
        # gates de homol permanecem
        assert len(registered_store.get_gates("svc-a", "homol")) == 1
        assert registered_store.get_gates("svc-a", "dev") == []

    def test_clear_when_no_gates(self, registered_store):
        result = clear_gates(registered_store, "svc-a", "prod")
        assert result["deleted_count"] == 0
