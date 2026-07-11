"""Tools de auditoria (async) contra store MySQL real (§16 / FID-02).

Cobre o fluxo completo — run_audit persistindo itens/status, get_audit_status,
submit_audit_approval, get_audit_report/list_audits, get_audit_gate_result e
set_service_criticality — todos sobre o ORM canônico, banco-por-tenant.
"""

from __future__ import annotations

import pytest

from src.tools.approval_tool import submit_audit_approval
from src.tools.audit_tool import get_audit_status, run_audit
from src.tools.gate_tool import get_audit_gate_result
from src.tools.policy_tool import set_service_criticality
from src.tools.report_tool import get_audit_report, list_audits

from .conftest import requires_mysql

pytestmark = [pytest.mark.integration, requires_mysql]


# ── run_audit — fluxo completo (checkers herméticos via tmp_repo) ─────────────
async def test_run_audit_full_flow(store_a, settings, tmp_repo, monkeypatch):
    monkeypatch.setattr(
        "src.checkers.lint_checker.LintChecker._run_ruff",
        staticmethod(lambda repo_path: (True, "ruff not installed (skipped)")),
    )
    result = await run_audit(store_a, settings, service="svc", repo="r", env="dev", repo_path=str(tmp_repo))
    assert result["audit_id"] == "audit_svc_dev"
    assert result["service"] == "svc"
    assert result["criticality"] == "medium"  # get_service_criticality default
    assert 0.0 <= result["score"] <= 1.0
    assert result["checklist_count"] > 0
    assert result["status"] in {"auto_approved", "pending_approval"}
    # a auditoria + itens foram persistidos
    stored = await store_a.get_latest_audit("svc", "dev")
    assert stored is not None
    assert len(await store_a.get_audit_items("audit_svc_dev")) == result["checklist_count"]


async def test_run_audit_auto_approves_high_score(store_a, settings, tmp_repo, monkeypatch):
    monkeypatch.setattr(
        "src.checkers.lint_checker.LintChecker._run_ruff",
        staticmethod(lambda repo_path: (True, "ok")),
    )
    (tmp_repo / "CHANGELOG.md").write_text("# changelog", encoding="utf-8")
    (tmp_repo / "Dockerfile").write_text("FROM python:3.12", encoding="utf-8")
    (tmp_repo / ".env.example").write_text("FOO=bar", encoding="utf-8")
    (tmp_repo / "tests" / "test_x.py").write_text("def test_x():\n    pass\n", encoding="utf-8")
    (tmp_repo / "README.md").write_text("# Repo\n## Environment variables\nFOO", encoding="utf-8")
    result = await run_audit(store_a, settings, service="svc", repo="r", env="dev", repo_path=str(tmp_repo))
    assert result["status"] == "auto_approved"
    assert result["approvals_required"] == 0


async def test_run_audit_uses_persisted_criticality(store_a, settings, tmp_repo, monkeypatch):
    """set_service_criticality passa a valer de verdade (antes era NO-OP=medium)."""
    monkeypatch.setattr(
        "src.checkers.lint_checker.LintChecker._run_ruff",
        staticmethod(lambda repo_path: (True, "ok")),
    )
    await store_a.set_service_criticality("svc", "high", "admin")
    result = await run_audit(store_a, settings, service="svc", repo="r", env="dev", repo_path=str(tmp_repo))
    assert result["criticality"] == "high"


# ── get_audit_status ──────────────────────────────────────────────────────────
async def test_get_audit_status_not_audited(store_a, settings):
    result = await get_audit_status(store_a, settings, service="none", env="dev")
    assert result["status"] == "not_audited"
    assert result["score"] is None


async def test_get_audit_status_after_audit(store_a, settings):
    await store_a.create_audit("svc", "r", "dev", "medium", 0.8, True, "approved", {})
    await store_a.add_audit_item("audit_svc_dev", "docs", "has_readme", True, True, "ok")
    await store_a.add_approval("audit_svc_dev", "a", "approved")
    result = await get_audit_status(store_a, settings, service="svc", env="dev")
    assert result["audit_id"] == "audit_svc_dev"
    assert result["status"] == "approved"
    assert result["items_count"] == 1
    assert result["approvals_count"] == 1


# ── submit_audit_approval ─────────────────────────────────────────────────────
async def _seed_audit(store_a):
    return await store_a.create_audit("svc", "r", "dev", "medium", 0.9, True, "pending_approval", {})


async def test_submit_approval_approved(store_a, settings):
    audit_id = await _seed_audit(store_a)
    result = await submit_audit_approval(
        store_a, settings, audit_id=audit_id, approved_by="alice", decision="approved", role="lead"
    )
    assert result["status"] == "approved"
    assert result["approvals_count"] == 1
    assert (await store_a.get_audit(audit_id))["status"] == "approved"


async def test_submit_approval_rejected(store_a, settings):
    audit_id = await _seed_audit(store_a)
    result = await submit_audit_approval(
        store_a, settings, audit_id=audit_id, approved_by="bob", decision="rejected"
    )
    assert result["status"] == "rejected"
    assert (await store_a.get_audit(audit_id))["passed"] is False


async def test_submit_approval_audit_not_found(store_a, settings):
    result = await submit_audit_approval(
        store_a, settings, audit_id="audit_missing_dev", approved_by="x", decision="approved"
    )
    assert result["error"] == "NotFound"


async def test_submit_approval_invalid_decision(store_a, settings):
    audit_id = await _seed_audit(store_a)
    result = await submit_audit_approval(
        store_a, settings, audit_id=audit_id, approved_by="x", decision="maybe"
    )
    assert result["error"] == "ValidationError"


# ── set_service_criticality (persiste) ────────────────────────────────────────
async def test_set_service_criticality_persists(store_a, settings):
    result = await set_service_criticality(
        store_a, settings, service="my-service", criticality="high", updated_by="admin"
    )
    assert result["success"] is True
    assert result["criticality"] == "high"
    assert await store_a.get_service_criticality("my-service") == "high"


# ── get_audit_report + list_audits ────────────────────────────────────────────
async def test_get_audit_report_empty(store_a, settings):
    result = await get_audit_report(store_a, settings)
    assert result["total_audits"] == 0
    assert result["average_score"] == 0.0


async def test_get_audit_report_with_data(store_a, settings):
    await store_a.create_audit("a", "r", "dev", "medium", 0.9, True, "approved", {})
    await store_a.create_audit("b", "r", "prod", "high", 0.4, False, "rejected", {})
    result = await get_audit_report(store_a, settings, period_days=365)
    assert result["total_audits"] == 2
    assert result["approved_count"] == 1
    assert result["rejected_count"] == 1
    assert "dev" in result["by_env"]
    assert "prod" in result["by_env"]
    assert result["pass_rate_pct"] == 50.0


async def test_list_audits_empty(store_a, settings):
    assert (await list_audits(store_a, settings))["total"] == 0


async def test_list_audits_with_results(store_a, settings):
    await store_a.create_audit("a", "r", "dev", "medium", 0.9, True, "approved", {})
    result = await list_audits(store_a, settings)
    assert result["total"] == 1
    assert result["audits"][0]["audit_id"] == "audit_a_dev"
    assert result["audits"][0]["service"] == "a"


# ── get_audit_gate_result ─────────────────────────────────────────────────────
async def test_get_audit_gate_result_no_audit(store_a, settings):
    result = await get_audit_gate_result(store_a, settings, service="test", env="dev")
    assert result["passed"] is False
    assert result["reason"] == "no_audit_found"


async def test_get_audit_gate_result_passed(store_a, settings):
    await store_a.create_audit("svc", "r", "prod", "high", 0.95, True, "approved", {})
    result = await get_audit_gate_result(store_a, settings, service="svc", env="prod")
    assert result["passed"] is True
    assert result["reason"] == "audit_approved"
    assert result["gate_type"] == "audit_compliance"
