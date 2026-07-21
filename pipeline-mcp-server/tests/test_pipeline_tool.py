"""Pipeline tools contra store MySQL real; o contrato é estritamente ledger-only."""

from __future__ import annotations

import pytest

from src.tools import (
    add_gate_result,
    approve_promotion,
    block_service,
    get_pipeline,
    get_pipeline_overview,
    get_promotion_history,
    list_pipeline,
    promote_service,
    register_pipeline,
    rollback,
    set_pipeline_config,
    watch_prs,
)

from .conftest import requires_mysql

pytestmark = [pytest.mark.integration, requires_mysql]


# ── básicos ───────────────────────────────────────────────────────────────────
async def test_register_get_list(store_a):
    reg = await register_pipeline(store_a, "svc", "o/svc")
    assert reg["action"] == "created"
    got = await get_pipeline(store_a, "svc")
    assert got["service"] == "svc"
    assert (await get_pipeline(store_a, "absent"))["error"] == "not_found"
    listed = await list_pipeline(store_a)
    assert listed["total"] == 1


# ── promote_service ───────────────────────────────────────────────────────────
async def test_promote_blocked_and_mismatch(store_a):
    await register_pipeline(store_a, "svc", "o/svc")
    await block_service(store_a, "svc", "risco", "ops")
    blocked = await promote_service(store_a, "svc", "dev", "homol", "u")
    assert blocked["error"] == "service_blocked"

    await register_pipeline(store_a, "svc2", "o/svc2")
    mismatch = await promote_service(store_a, "svc2", "homol", "prod", "u")
    assert mismatch["error"] == "env_mismatch"


async def test_promote_missing_gate_fails_closed(store_a):
    await register_pipeline(store_a, "svc", "o/svc")
    await set_pipeline_config(store_a, "svc", {"homol": ["qa_tests"]})
    result = await promote_service(store_a, "svc", "dev", "homol", "u")

    assert result["can_promote"] is False
    assert result["can_recommend"] is False
    assert result["promoted"] is False
    assert result["status"] == "gates_not_evaluated"
    assert result["missing_gates"] == ["qa_tests"]
    assert result["failed_gates"] == []
    assert result["external_action_performed"] is False
    assert (await get_promotion_history(store_a))["total"] == 0


async def test_promote_empty_gate_configuration_fails_closed(store_a):
    await register_pipeline(store_a, "svc", "o/svc")
    await set_pipeline_config(store_a, "svc", {"homol": []})
    result = await promote_service(store_a, "svc", "dev", "homol", "u")

    assert result["gates_configured"] is False
    assert result["gate_status"] == "gates_not_configured"
    assert result["can_promote"] is False
    assert result["can_recommend"] is False
    assert result["promoted"] is False
    assert (await get_promotion_history(store_a))["total"] == 0


async def test_promote_records_recommendation_only(store_a):
    await register_pipeline(store_a, "svc", "o/svc")
    await set_pipeline_config(store_a, "svc", {"homol": ["qa_tests"]})
    await add_gate_result(store_a, "svc", "dev", "qa_tests", True)

    result = await promote_service(store_a, "svc", "dev", "homol", "u", "motivo")

    assert result["can_promote"] is False
    assert result["can_recommend"] is True
    assert result["promotion_recommended"] is True
    assert result["promoted"] is False
    assert result["status"] == "pending_human_approval"
    assert result["pr_number"] is None
    assert result["pr_url"] is None
    assert result["external_action_performed"] is False
    assert (await get_pipeline(store_a, "svc"))["current_env"] == "dev"

    promotion = await store_a.get_promotion(result["promotion_id"])
    assert promotion["status"] == "pending_human_approval"
    assert promotion["completed_at"] is None


# ── approve_promotion ─────────────────────────────────────────────────────────
async def test_approve_not_found_and_invalid_status(store_a):
    assert (await approve_promotion(store_a, 999, "a"))["error"] == "not_found"
    await register_pipeline(store_a, "svc", "o/svc")
    pid = await store_a.add_promotion(
        "svc", "dev", "homol", "u", None, {}, "homol", "pending_external_execution"
    )
    assert (await approve_promotion(store_a, pid, "a"))["error"] == "invalid_status"


async def test_approve_records_human_decision_without_execution(store_a):
    await register_pipeline(store_a, "svc", "o/svc")
    await set_pipeline_config(store_a, "svc", {"homol": ["qa_tests"]})
    await add_gate_result(store_a, "svc", "dev", "qa_tests", True)
    recommendation = await promote_service(store_a, "svc", "dev", "homol", "u")

    result = await approve_promotion(store_a, recommendation["promotion_id"], "boss")

    assert result["approved"] is True
    assert result["approval_recorded"] is True
    assert result["status"] == "pending_external_execution"
    assert result["promoted"] is False
    assert result["merge_sha"] is None
    assert result["external_action_performed"] is False
    assert (await get_pipeline(store_a, "svc"))["current_env"] == "dev"

    promotion = await store_a.get_promotion(recommendation["promotion_id"])
    assert promotion["status"] == "pending_external_execution"
    assert promotion["approved_by"] == "boss"
    assert promotion["approved_at"] is not None
    assert promotion["completed_at"] is None


async def test_approve_revalidates_gates_fail_closed(store_a):
    await register_pipeline(store_a, "svc", "o/svc")
    await set_pipeline_config(store_a, "svc", {"homol": ["qa_tests"]})
    await add_gate_result(store_a, "svc", "dev", "qa_tests", True)
    recommendation = await promote_service(store_a, "svc", "dev", "homol", "u")
    await add_gate_result(store_a, "svc", "dev", "qa_tests", False)

    result = await approve_promotion(store_a, recommendation["promotion_id"], "boss")

    assert result["approved"] is False
    assert result["approval_recorded"] is False
    assert result["status"] == "gates_failed"
    assert result["failed_gates"] == ["qa_tests"]
    assert result["external_action_performed"] is False
    promotion = await store_a.get_promotion(recommendation["promotion_id"])
    assert promotion["status"] == "pending_human_approval"
    assert promotion["approved_at"] is None


async def test_approve_rejects_stale_environment(store_a):
    await register_pipeline(store_a, "svc", "o/svc")
    await set_pipeline_config(store_a, "svc", {"homol": ["qa_tests"]})
    await add_gate_result(store_a, "svc", "dev", "qa_tests", True)
    recommendation = await promote_service(store_a, "svc", "dev", "homol", "u")
    await store_a.update_pipeline_env("svc", "homol")

    result = await approve_promotion(store_a, recommendation["promotion_id"], "boss")

    assert result["error"] == "env_mismatch"
    assert result["approved"] is False
    assert result["approval_recorded"] is False
    assert result["external_action_performed"] is False
    promotion = await store_a.get_promotion(recommendation["promotion_id"])
    assert promotion["status"] == "pending_human_approval"
    assert promotion["approved_at"] is None


# ── watch_prs ─────────────────────────────────────────────────────────────────
async def test_watch_prs_uses_only_registered_ledger_data(store_a):
    await register_pipeline(store_a, "svc", "o/svc")

    incomplete = await watch_prs(store_a, repos=["o/svc", "o/unregistered"])

    assert incomplete["ledger_only"] is True
    assert incomplete["external_query_performed"] is False
    assert incomplete["repos_checked"] == 0
    assert incomplete["prs_observed"] == 0
    assert incomplete["auto_approved_count"] == 0
    assert incomplete["auto_merged_count"] == 0
    assert incomplete["unregistered_repos"] == ["o/unregistered"]
    recommendation = incomplete["recommendations"][0]
    assert recommendation["pr_state"] == "not_observed"
    assert recommendation["status"] == "gates_not_evaluated"
    assert recommendation["can_recommend"] is False
    assert recommendation["gates_satisfied"] is False
    assert (
        recommendation["recommended_action"]
        == "complete_or_fix_gates_before_human_review"
    )
    assert incomplete["waiting_human_count"] == 0

    await add_gate_result(store_a, "svc", "dev", "audit_compliance", True)
    ready = await watch_prs(store_a, repos=["o/svc"])
    recommendation = ready["recommendations"][0]
    assert recommendation["gates_satisfied"] is True
    assert recommendation["can_recommend"] is True
    assert recommendation["status"] == "pending_human_approval"
    assert recommendation["recommended_action"] == "human_review_required"
    assert ready["external_query_performed"] is False
    assert ready["auto_approved"] == []
    assert ready["waiting_human_count"] == 1


async def test_watch_prs_does_not_recommend_blocked_service(store_a):
    await register_pipeline(store_a, "svc", "o/svc")
    await add_gate_result(store_a, "svc", "dev", "audit_compliance", True)
    await block_service(store_a, "svc", "risco", "ops")

    result = await watch_prs(store_a)

    recommendation = result["recommendations"][0]
    assert recommendation["status"] == "service_blocked"
    assert recommendation["can_recommend"] is False
    assert (
        recommendation["recommended_action"]
        == "resolve_service_block_before_human_review"
    )
    assert result["waiting_human_count"] == 0


# ── rollback / history / overview ─────────────────────────────────────────────
async def test_rollback_registers_request_without_changing_environment(store_a):
    await register_pipeline(store_a, "svc", "o/svc")

    mismatch = await rollback(store_a, "svc", "prod", "v1", "ops")
    assert mismatch["error"] == "env_mismatch"
    assert mismatch["rolled_back"] is False

    result = await rollback(store_a, "svc", "dev", "v1", "ops", "motivo")
    assert result["rollback_requested"] is True
    assert result["rolled_back"] is False
    assert result["status"] == "pending_human_approval"
    assert result["external_action_performed"] is False
    assert (await get_pipeline(store_a, "svc"))["current_env"] == "dev"
    promotion = await store_a.get_promotion(result["promotion_id"])
    assert promotion["status"] == "pending_human_approval"
    assert promotion["to_env"] == "rollback"
    assert promotion["completed_at"] is None

    assert (await rollback(store_a, "absent", "dev", "v1", "ops"))[
        "error"
    ] == "not_found"


async def test_history_and_overview(store_a):
    await register_pipeline(store_a, "svc", "o/svc")
    hist = await get_promotion_history(store_a)
    assert hist["limit"] == 20
    overview = await get_pipeline_overview(store_a)
    assert overview["total_services"] == 1
    assert (await set_pipeline_config(store_a, "absent", {}))["error"] == "not_found"
    assert (await block_service(store_a, "absent", "r", "a"))["error"] == "not_found"
