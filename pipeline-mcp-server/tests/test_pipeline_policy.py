"""Contrato fail-closed puro, independente de banco ou executor externo."""

from __future__ import annotations

from inspect import signature

from src.tools.pipeline_tool import (
    _assess_required_gates,
    approve_promotion,
    promote_service,
    rollback,
    watch_prs,
)


def _pipeline(config: dict[str, list[str]]) -> dict:
    return {"service": "svc", "gates_config": config}


def test_unconfigured_gates_never_satisfy_policy():
    result = _assess_required_gates(
        _pipeline({"homol": []}),
        [{"gate_type": "qa_tests", "passed": True}],
        "homol",
    )

    assert result["gates_configured"] is False
    assert result["gates_satisfied"] is False
    assert result["gate_status"] == "gates_not_configured"
    assert result["required_gates"] == []


def test_missing_gate_never_satisfies_policy():
    result = _assess_required_gates(
        _pipeline({"homol": ["qa_tests", "security_scan"]}),
        [{"gate_type": "qa_tests", "passed": True}],
        "homol",
    )

    assert result["gates_satisfied"] is False
    assert result["gate_status"] == "gates_not_evaluated"
    assert result["missing_gates"] == ["security_scan"]
    assert result["gates_snapshot"] == {"qa_tests": True, "security_scan": None}


def test_failed_gate_never_satisfies_policy():
    result = _assess_required_gates(
        _pipeline({"homol": ["qa_tests"]}),
        [{"gate_type": "qa_tests", "passed": False}],
        "homol",
    )

    assert result["gates_satisfied"] is False
    assert result["gate_status"] == "gates_failed"
    assert result["failed_gates"] == ["qa_tests"]


def test_all_required_recorded_gates_may_support_recommendation():
    result = _assess_required_gates(
        _pipeline({"homol": ["qa_tests", "qa_tests"]}),
        [{"gate_type": "qa_tests", "passed": True}],
        "homol",
    )

    assert result["gates_satisfied"] is True
    assert result["gate_status"] == "gates_satisfied"
    assert result["required_gates"] == ["qa_tests"]


def test_execution_tools_accept_no_external_provider_credentials():
    for tool in (promote_service, approve_promotion, watch_prs):
        parameters = signature(tool).parameters
        assert "github_token" not in parameters
        assert "github_org" not in parameters


async def test_audit_actors_cannot_be_empty():
    inert_store = object()

    promote = await promote_service(inert_store, "svc", "dev", "homol", "  ")  # type: ignore[arg-type]
    approve = await approve_promotion(inert_store, 1, "\t")  # type: ignore[arg-type]
    rollback_result = await rollback(
        inert_store, "svc", "dev", "sha256:x", "\n"  # type: ignore[arg-type]
    )

    assert promote["error"] == "invalid_promoted_by"
    assert promote["can_recommend"] is False
    assert approve["error"] == "invalid_approved_by"
    assert approve["approval_recorded"] is False
    assert rollback_result["error"] == "invalid_rolled_back_by"
    assert rollback_result["rollback_requested"] is False
