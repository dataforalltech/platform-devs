"""Testes dos modelos Pydantic e do enum de criticidade."""

from src.models.criticality import Criticality
from src.models.policy import (
    ApprovalRule,
    AuditResult,
    ChecklistItem,
    CompliancePolicy,
)


def test_criticality_values():
    """O enum expõe os quatro níveis como strings."""
    assert Criticality.LOW == "low"
    assert Criticality.MEDIUM == "medium"
    assert Criticality.HIGH == "high"
    assert Criticality.CRITICAL == "critical"
    assert [c.value for c in Criticality] == ["low", "medium", "high", "critical"]


def test_checklist_item_defaults():
    """ChecklistItem tem passed/details opcionais."""
    item = ChecklistItem(category="structure", name="has_src_dir", required=True)
    assert item.passed is None
    assert item.details is None


def test_compliance_policy_model():
    """CompliancePolicy valida a estrutura dos checkers."""
    policy = CompliancePolicy(
        env="dev",
        min_score=0.5,
        required_checkers={"structure": ["has_src_dir"]},
        ideal_checkers={"tests": ["min_coverage_60"]},
    )
    assert policy.env == "dev"
    assert policy.required_checkers["structure"] == ["has_src_dir"]


def test_audit_result_model():
    """AuditResult aceita checklist como lista de ChecklistItem."""
    result = AuditResult(
        audit_id="audit_x_dev",
        service="x",
        repo="r",
        env="dev",
        criticality="medium",
        score=0.8,
        passed=True,
        status="approved",
        checklist=[ChecklistItem(category="docs", name="has_readme", required=True, passed=True)],
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
    )
    assert result.checklist[0].name == "has_readme"
    assert result.passed is True


def test_approval_rule_defaults():
    """ApprovalRule tem todos os campos opcionais."""
    rule = ApprovalRule()
    assert rule.auto_approve_if_score is None
    assert rule.required_approvals is None
    assert rule.required_roles is None

    populated = ApprovalRule(
        auto_approve_if_score=0.7, required_approvals=2, required_roles=["lead"]
    )
    assert populated.required_roles == ["lead"]
