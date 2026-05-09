"""Pydantic models para deploy-mcp-server."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# ── Tipos literais ─────────────────────────────────────────────────────────── #
Environment = Literal["dev", "hml", "prod"]
MergeMethod = Literal["squash", "merge", "rebase"]
PRState = Literal["open", "closed", "all"]
WorkflowRunStatus = Literal["queued", "in_progress", "completed"]
WorkflowRunConclusion = Literal[
    "success", "failure", "cancelled", "skipped", "timed_out", "action_required", "neutral"
]


# ── Git ────────────────────────────────────────────────────────────────────── #
class FileChange(BaseModel):
    """Um arquivo a ser criado/atualizado num commit."""

    path: str = Field(..., description="Caminho relativo ao root do repo (ex: src/app/main.py).")
    content: str = Field(..., description="Conteúdo completo do arquivo em texto.")


# ── PR ────────────────────────────────────────────────────────────────────── #
class CheckRun(BaseModel):
    name: str
    status: str
    conclusion: str | None = None
    url: str


class PRInfo(BaseModel):
    number: int
    title: str
    state: str
    url: str
    head: str
    base: str
    head_sha: str
    mergeable: bool | None = None
    mergeable_state: str | None = None
    draft: bool = False
    checks: list[CheckRun] = Field(default_factory=list)


# ── Workflow ──────────────────────────────────────────────────────────────── #
class WorkflowRunInfo(BaseModel):
    id: int
    name: str | None = None
    status: str
    conclusion: str | None = None
    head_branch: str | None = None
    head_sha: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    url: str
    logs_url: str | None = None


# ── Deploy ────────────────────────────────────────────────────────────────── #
class DeployResult(BaseModel):
    dispatched: bool
    workflow: str
    ref: str
    repo: str
    environment: Environment
    service: str
    hint: str = "Use list_workflow_runs para acompanhar o status."
