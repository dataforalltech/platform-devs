"""Suíte hermética do contrato ledger-only das tools de pipeline.

O fake mantém somente o estado necessário à unidade sob teste e falha imediatamente
se o código tentar alterar ambiente ou concluir uma promoção como execução real.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from src.tools.pipeline_tool import (
    approve_promotion,
    promote_service,
    rollback,
    watch_prs,
)


class FakeStore:
    def __init__(self) -> None:
        self.pipelines: dict[str, dict[str, Any]] = {}
        self.gates: dict[tuple[str, str], list[dict[str, Any]]] = {}
        self.promotions: dict[int, dict[str, Any]] = {}
        self.next_promotion_id = 1
        self.environment_update_attempts = 0
        self.completion_attempts = 0

    def add_pipeline(
        self,
        service: str,
        *,
        gates_config: dict[str, list[str]] | None = None,
        current_env: str = "dev",
        blocked: bool = False,
    ) -> None:
        self.pipelines[service] = {
            "service": service,
            "repo": f"org/{service}",
            "current_env": current_env,
            "current_version": "sha256:current",
            "blocked": int(blocked),
            "block_reason": "mudança bloqueada" if blocked else None,
            "gates_config": deepcopy(gates_config) if gates_config is not None else {},
        }

    def set_gate(
        self,
        service: str,
        env: str,
        gate_type: str,
        passed: bool,
    ) -> None:
        rows = self.gates.setdefault((service, env), [])
        rows[:] = [row for row in rows if row["gate_type"] != gate_type]
        rows.append({"gate_type": gate_type, "passed": int(passed)})

    def env_snapshot(self) -> dict[str, tuple[str, str]]:
        return {
            service: (pipeline["current_env"], pipeline["current_version"])
            for service, pipeline in self.pipelines.items()
        }

    async def get_pipeline(self, service: str) -> dict[str, Any] | None:
        return self.pipelines.get(service)

    async def list_pipelines(
        self, env: str | None = None, status: str | None = None
    ) -> list[dict[str, Any]]:
        pipelines = list(self.pipelines.values())
        if env is not None:
            pipelines = [row for row in pipelines if row["current_env"] == env]
        if status == "blocked":
            pipelines = [row for row in pipelines if row["blocked"]]
        elif status == "active":
            pipelines = [row for row in pipelines if not row["blocked"]]
        return pipelines

    async def get_gates(self, service: str, env: str) -> list[dict[str, Any]]:
        return deepcopy(self.gates.get((service, env), []))

    async def add_promotion(
        self,
        service: str,
        from_env: str,
        to_env: str,
        promoted_by: str,
        reason: str | None,
        gates_snapshot: dict[str, bool | None],
        deploy_ref: str | None,
        status: str,
        pr_number: int | None = None,
        pr_url: str | None = None,
    ) -> int:
        promotion_id = self.next_promotion_id
        self.next_promotion_id += 1
        self.promotions[promotion_id] = {
            "id": promotion_id,
            "service": service,
            "from_env": from_env,
            "to_env": to_env,
            "promoted_by": promoted_by,
            "reason": reason,
            "gates_snapshot": deepcopy(gates_snapshot),
            "deploy_ref": deploy_ref,
            "status": status,
            "pr_number": pr_number,
            "pr_url": pr_url,
            "approved_by": None,
            "approved_at": None,
            "completed_at": None,
        }
        return promotion_id

    async def get_promotion(self, promotion_id: int) -> dict[str, Any] | None:
        return self.promotions.get(promotion_id)

    async def approve_promotion(
        self, promotion_id: int, approved_by: str
    ) -> dict[str, Any] | None:
        promotion = self.promotions.get(promotion_id)
        if promotion is None:
            return None
        promotion.update(
            {
                "approved_by": approved_by,
                "approved_at": "2026-07-21T00:00:00+00:00",
                "status": "pending_external_execution",
            }
        )
        return promotion

    async def update_pipeline_env(
        self, service: str, env: str, version: str | None = None
    ) -> None:
        self.environment_update_attempts += 1
        raise AssertionError(
            f"tool ledger-only tentou alterar ambiente: {service} -> {env} ({version})"
        )

    async def complete_promotion(self, promotion_id: int, status: str) -> None:
        self.completion_attempts += 1
        raise AssertionError(
            f"tool ledger-only tentou concluir promoção {promotion_id} como {status}"
        )


def assert_no_execution(
    store: FakeStore, before: dict[str, tuple[str, str]], result: dict
) -> None:
    assert result["external_action_performed"] is False
    assert store.env_snapshot() == before
    assert store.environment_update_attempts == 0
    assert store.completion_attempts == 0


@pytest.mark.parametrize(
    ("gates_config", "gate_result", "expected_status"),
    [
        ({}, None, "gates_not_configured"),
        ({"homol": []}, None, "gates_not_configured"),
        ({"homol": ["qa_tests"]}, None, "gates_not_evaluated"),
        ({"homol": ["qa_tests"]}, False, "gates_failed"),
    ],
    ids=["config-ausente", "config-vazia", "gate-ausente", "gate-falho"],
)
async def test_promote_fails_closed_without_satisfied_gates(
    gates_config: dict[str, list[str]],
    gate_result: bool | None,
    expected_status: str,
) -> None:
    store = FakeStore()
    store.add_pipeline("svc", gates_config=gates_config)
    if gate_result is not None:
        store.set_gate("svc", "dev", "qa_tests", gate_result)
    before = store.env_snapshot()

    result = await promote_service(store, "svc", "dev", "homol", "requester")  # type: ignore[arg-type]

    assert result["status"] == expected_status
    assert result["can_promote"] is False
    assert result["can_recommend"] is False
    assert result["promoted"] is False
    assert store.promotions == {}
    assert_no_execution(store, before, result)


async def test_promote_with_satisfied_gates_registers_recommendation_only() -> None:
    store = FakeStore()
    store.add_pipeline("svc", gates_config={"homol": ["qa_tests"]})
    store.set_gate("svc", "dev", "qa_tests", True)
    before = store.env_snapshot()

    result = await promote_service(store, "svc", "dev", "homol", "requester")  # type: ignore[arg-type]

    assert result["status"] == "pending_human_approval"
    assert result["can_promote"] is False
    assert result["can_recommend"] is True
    assert result["promotion_recommended"] is True
    assert result["promoted"] is False
    promotion = store.promotions[result["promotion_id"]]
    assert promotion["status"] == "pending_human_approval"
    assert promotion["completed_at"] is None
    assert_no_execution(store, before, result)


@pytest.mark.parametrize(
    ("blocked", "current_env", "expected_error"),
    [(True, "dev", "service_blocked"), (False, "homol", "env_mismatch")],
    ids=["servico-bloqueado", "ambiente-divergente"],
)
async def test_promote_blocked_or_mismatched_never_mutates_environment(
    blocked: bool, current_env: str, expected_error: str
) -> None:
    store = FakeStore()
    store.add_pipeline(
        "svc",
        gates_config={"homol": ["qa_tests"]},
        current_env=current_env,
        blocked=blocked,
    )
    store.set_gate("svc", "dev", "qa_tests", True)
    before = store.env_snapshot()

    result = await promote_service(store, "svc", "dev", "homol", "requester")  # type: ignore[arg-type]

    assert result["error"] == expected_error
    assert result["can_promote"] is False
    assert store.promotions == {}
    assert_no_execution(store, before, result)


async def test_approve_revalidates_gates_before_recording_human_decision() -> None:
    store = FakeStore()
    store.add_pipeline("svc", gates_config={"homol": ["qa_tests"]})
    store.set_gate("svc", "dev", "qa_tests", True)
    recommendation = await promote_service(store, "svc", "dev", "homol", "requester")  # type: ignore[arg-type]
    store.set_gate("svc", "dev", "qa_tests", False)
    before = store.env_snapshot()

    result = await approve_promotion(store, recommendation["promotion_id"], "approver")  # type: ignore[arg-type]

    assert result["status"] == "gates_failed"
    assert result["approved"] is False
    assert result["approval_recorded"] is False
    promotion = store.promotions[recommendation["promotion_id"]]
    assert promotion["status"] == "pending_human_approval"
    assert promotion["approved_by"] is None
    assert_no_execution(store, before, result)


async def test_approve_records_pending_external_execution_without_promotion() -> None:
    store = FakeStore()
    store.add_pipeline("svc", gates_config={"homol": ["qa_tests"]})
    store.set_gate("svc", "dev", "qa_tests", True)
    recommendation = await promote_service(store, "svc", "dev", "homol", "requester")  # type: ignore[arg-type]
    before = store.env_snapshot()

    result = await approve_promotion(store, recommendation["promotion_id"], "approver")  # type: ignore[arg-type]

    assert result["status"] == "pending_external_execution"
    assert result["approved"] is True
    assert result["approval_recorded"] is True
    assert result["promoted"] is False
    promotion = store.promotions[recommendation["promotion_id"]]
    assert promotion["status"] == "pending_external_execution"
    assert promotion["completed_at"] is None
    assert_no_execution(store, before, result)


async def test_watch_prs_is_ledger_only_and_recommends_only_ready_service() -> None:
    store = FakeStore()
    store.add_pipeline("config-absent", gates_config={})
    store.add_pipeline("config-empty", gates_config={"dev": []})
    store.add_pipeline("gate-missing", gates_config={"dev": ["audit_compliance"]})
    store.add_pipeline("gate-failed", gates_config={"dev": ["audit_compliance"]})
    store.add_pipeline("ready", gates_config={"dev": ["audit_compliance"]})
    store.add_pipeline(
        "blocked", gates_config={"dev": ["audit_compliance"]}, blocked=True
    )
    store.set_gate("gate-failed", "dev", "audit_compliance", False)
    store.set_gate("ready", "dev", "audit_compliance", True)
    store.set_gate("blocked", "dev", "audit_compliance", True)
    before = store.env_snapshot()

    result = await watch_prs(store)  # type: ignore[arg-type]

    by_service = {item["service"]: item for item in result["recommendations"]}
    assert by_service["config-absent"]["status"] == "gates_not_configured"
    assert by_service["config-empty"]["status"] == "gates_not_configured"
    assert by_service["gate-missing"]["status"] == "gates_not_evaluated"
    assert by_service["gate-failed"]["status"] == "gates_failed"
    assert by_service["ready"]["status"] == "pending_human_approval"
    assert by_service["blocked"]["status"] == "service_blocked"
    assert result["waiting_human_count"] == 1
    assert [item["service"] for item in result["waiting_human"]] == ["ready"]
    assert result["external_query_performed"] is False
    assert result["prs_observed"] == 0
    assert result["auto_approved_count"] == 0
    assert result["auto_merged_count"] == 0
    assert_no_execution(store, before, result)


async def test_rollback_registers_request_without_changing_environment() -> None:
    store = FakeStore()
    store.add_pipeline("svc", gates_config={"dev": ["audit_compliance"]})
    before = store.env_snapshot()

    result = await rollback(store, "svc", "dev", "sha256:previous", "operator")  # type: ignore[arg-type]

    assert result["rollback_requested"] is True
    assert result["rolled_back"] is False
    assert result["status"] == "pending_human_approval"
    promotion = store.promotions[result["promotion_id"]]
    assert promotion["to_env"] == "rollback"
    assert promotion["deploy_ref"] == "sha256:previous"
    assert promotion["completed_at"] is None
    assert_no_execution(store, before, result)


async def test_rollback_env_mismatch_fails_without_registering_request() -> None:
    store = FakeStore()
    store.add_pipeline("svc", current_env="dev")
    before = store.env_snapshot()

    result = await rollback(store, "svc", "prod", "sha256:previous", "operator")  # type: ignore[arg-type]

    assert result["error"] == "env_mismatch"
    assert result["rolled_back"] is False
    assert store.promotions == {}
    assert_no_execution(store, before, result)
