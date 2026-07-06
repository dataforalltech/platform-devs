"""Typed contracts for the dev-agent Plan-Approve-Execute cycle.

Copied (in *form*) from the marketing agent's ``models/plan.py`` triad
(PlanItem / Plan / ItemResult) and adapted for the DevTeam:

- ``tool`` is a namespaced gateway operation ``<namespace>.<operationId>``
  (never a REST endpoint); a field validator enforces the shape.
- ``capability`` and ``risk`` are attached to each item (enforcement ON).
- DAG traceability fields: ``runbook_id`` / ``task_id`` / ``depends_on`` and
  ``runbook_version`` on the plan.
- per-item ``idempotency_key`` and a ``required`` flag (drives final status).
"""

from __future__ import annotations

import uuid
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class Capability(StrEnum):
    READ = "read"
    WRITE = "write"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ItemStatus(StrEnum):
    PENDING = "pending"
    READY = "ready"  # dependencies satisfied, awaiting execution
    APPROVED = "approved"  # high-risk gate cleared individually
    EXECUTING = "executing"
    DONE = "done"
    ERROR = "error"
    SKIPPED = "skipped"  # dependency failed / not selected
    NEEDS_RECONFIRM = "needs_reconfirm"  # orphaned/EXECUTING on resume -> reconcile


class PlanStatus(StrEnum):
    PENDING = "pending"  # awaiting approval
    APPROVED = "approved"  # approved, not yet started
    EXECUTING = "executing"
    DONE = "done"
    PARTIAL = "partial"  # done_count < total, no blocking failures
    FAILED = "failed"  # blocking failure
    REJECTED = "rejected"
    EXPIRED = "expired"  # approval TTL elapsed with no human response


class PlanItem(BaseModel):
    """An atomic action of the plan, bound to ONE gateway tool."""

    item_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    plan_id: str
    sequence_num: int

    # Runbook origin (DAG traceability)
    runbook_id: str
    task_id: str  # task key within the runbook
    depends_on: list[str] = Field(default_factory=list)  # task_ids of the SAME plan

    # Concrete action — ALWAYS a gateway tool, never a REST endpoint
    tool: str  # "<namespace>.<operationId>", e.g. "qa-mcp.run_tests"
    capability: Capability  # attached to the item (write/read) — enforcement ON
    risk: RiskLevel = RiskLevel.LOW  # high => requires individual approval

    # Whether this task is required for the plan to be considered DONE.
    # A required item that fails => FAILED; an optional item that fails => PARTIAL.
    required: bool = True

    label: str = Field(max_length=120)
    description: str | None = None
    responsible: str  # persona/role owning the step (security, qa-engineer, ...)
    input_data: dict[str, Any] = Field(default_factory=dict)

    # Per-item idempotency (does NOT exist in the marketing agent)
    idempotency_key: str = Field(default_factory=lambda: str(uuid.uuid4()))

    status: ItemStatus = ItemStatus.PENDING
    output_json: dict[str, Any] | None = None
    error_text: str | None = None

    @field_validator("tool")
    @classmethod
    def _tool_is_namespaced(cls, v: str) -> str:
        if "." not in v or v.startswith("http") or " " in v:
            raise ValueError(
                "tool must be '<namespace>.<operationId>' (gateway MCP), "
                f"received: {v!r}"
            )
        return v


class Plan(BaseModel):
    """Structured plan derived from a runbook DAG, before execution."""

    plan_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str
    run_id: str | None = None

    # 1:1 correlation with the approval poll (copied from the marketing agent)
    question_id: str = Field(default_factory=lambda: f"plan_{uuid.uuid4().hex[:16]}")

    runbook_id: str
    runbook_version: str  # versioned DAG — pins the plan origin
    title: str
    summary: str
    explanation: str  # markdown shown to the human
    responsible_profile: str

    status: PlanStatus = PlanStatus.PENDING
    items: list[PlanItem]

    def requires_high_risk_approval(self) -> bool:
        return any(i.risk is RiskLevel.HIGH for i in self.items)

    def item_by_task(self, task_id: str) -> PlanItem | None:
        return next((i for i in self.items if i.task_id == task_id), None)


class ItemResult(BaseModel):
    """Result of executing an item (executor return value)."""

    item_id: str
    task_id: str
    tool: str
    status: ItemStatus  # done | error | skipped
    output: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
