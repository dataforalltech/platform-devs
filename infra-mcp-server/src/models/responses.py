"""Modelos Pydantic de resposta das tools."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class CommandSummary(BaseModel):
    """Resumo de invocação de subprocess — anexado a toda resposta de tool."""

    cmd: str
    exit_code: int
    duration_ms: int
    truncated: bool = False


class ValidationFinding(BaseModel):
    """Item retornado por terraform_validate."""

    severity: str = Field(description="error | warning | info")
    summary: str
    detail: str | None = None
    range: dict[str, Any] | None = Field(
        default=None, description="filename + line do erro, quando aplicável"
    )


class PlanSummary(BaseModel):
    """Resumo de terraform plan."""

    has_changes: bool
    add: int = 0
    change: int = 0
    destroy: int = 0
    plan_path: str | None = Field(
        default=None, description="Caminho do arquivo .tfplan binário (input para infracost/show)."
    )
    changed_resources: list[str] = Field(default_factory=list)


class CheckovFinding(BaseModel):
    """Item retornado por checkov."""

    check_id: str
    severity: str
    resource: str
    file_path: str | None = None
    file_line_range: list[int] = Field(default_factory=list)
    description: str | None = None
    guideline: str | None = None


class CostEstimate(BaseModel):
    """Resultado de infracost diff."""

    monthly_diff_usd: float
    monthly_baseline_usd: float | None = None
    monthly_after_usd: float | None = None
    diff_percentage: float | None = None
    breakdown: list[dict[str, Any]] = Field(default_factory=list)


class ToolErrorResponse(BaseModel):
    """Resposta padrão para erros."""

    error: str
    details: str | None = None
    tool: str | None = None
    cmd: str | None = None
