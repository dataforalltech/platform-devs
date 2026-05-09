from typing import Any

from pydantic import BaseModel


class ChecklistItem(BaseModel):
    category: str
    name: str
    required: bool
    passed: bool | None = None
    details: str | None = None


class CompliancePolicy(BaseModel):
    env: str
    min_score: float
    required_checkers: dict[str, list[str]]
    ideal_checkers: dict[str, list[str]]


class AuditResult(BaseModel):
    audit_id: str
    service: str
    repo: str
    env: str
    criticality: str
    score: float
    passed: bool
    status: str
    checklist: list[ChecklistItem]
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class ApprovalRule(BaseModel):
    auto_approve_if_score: float | None = None
    required_approvals: int | None = None
    required_roles: list[str] | None = None
