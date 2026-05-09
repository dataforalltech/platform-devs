"""cost_estimate_infracost: roda infracost diff sobre um terraform plan binário."""

from __future__ import annotations

import json

from ..config.settings import Settings
from ..utils.subprocess_runner import (
    BinaryNotFound,
    CommandTimeout,
    run_command,
)
from ..utils.validators import normalize_path

# Threshold default conforme cicd-deploy.md §4 #4: +US$ 100/mês ou +20%.
_DEFAULT_DELTA_USD_THRESHOLD = 100.0
_DEFAULT_DELTA_PCT_THRESHOLD = 20.0


def cost_estimate_infracost(
    settings: Settings,
    plan_path: str,
    delta_usd_threshold: float | None = None,
    delta_pct_threshold: float | None = None,
) -> dict:
    """Roda `infracost diff --path <tfplan> --format json`.

    Args:
        plan_path: arquivo .tfplan binário (output de terraform_plan).
        delta_usd_threshold: se delta > este valor, marca hard_stop=True. Default 100 USD/mês.
        delta_pct_threshold: se delta% > este valor, marca hard_stop=True. Default 20%.

    Retorna delta de custo + breakdown + flag hard_stop conforme thresholds.
    """
    try:
        plan_file = normalize_path(plan_path, "plan_path")
    except ValueError as e:
        return {"error": "validation_error", "details": str(e), "tool": "cost_estimate_infracost"}

    if not plan_file.exists():
        return {
            "error": "plan_not_found",
            "details": f"Arquivo {plan_file} não existe",
            "tool": "cost_estimate_infracost",
        }

    threshold_usd = (
        delta_usd_threshold if delta_usd_threshold is not None else _DEFAULT_DELTA_USD_THRESHOLD
    )
    threshold_pct = (
        delta_pct_threshold if delta_pct_threshold is not None else _DEFAULT_DELTA_PCT_THRESHOLD
    )

    try:
        result = run_command(
            [
                settings.infracost_bin,
                "diff",
                "--path",
                str(plan_file),
                "--format",
                "json",
                "--no-color",
            ],
            cwd=plan_file.parent,
            timeout=settings.cost_timeout,
            output_max_chars=settings.output_max_chars,
        )
    except (BinaryNotFound, CommandTimeout) as e:
        if isinstance(e, BinaryNotFound):
            return {
                "error": "binary_not_found",
                "details": str(e),
                "tool": "cost_estimate_infracost",
            }
        return {"error": "timeout", "details": str(e), "tool": "cost_estimate_infracost"}

    if result.exit_code != 0 and not result.stdout.strip():
        return {
            "error": "infracost_failed",
            "details": result.stderr or "infracost retornou erro sem JSON",
            "tool": "cost_estimate_infracost",
            "command": _cmd_summary(result),
        }

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        return {
            "error": "invalid_json",
            "details": str(e),
            "stdout_preview": result.stdout[:1000],
            "tool": "cost_estimate_infracost",
            "command": _cmd_summary(result),
        }

    # infracost root: { "diffTotalMonthlyCost": "1.23", "currency": "USD",
    #                  "projects": [ { "diff": { ... }, "breakdown": {...} } ] }
    diff_total_str = data.get("diffTotalMonthlyCost")
    try:
        monthly_diff = float(diff_total_str) if diff_total_str is not None else 0.0
    except (TypeError, ValueError):
        monthly_diff = 0.0

    past_total_str = data.get("pastTotalMonthlyCost")
    after_total_str = data.get("totalMonthlyCost")
    monthly_baseline = _safe_float(past_total_str)
    monthly_after = _safe_float(after_total_str)

    pct = None
    if monthly_baseline and monthly_baseline > 0:
        pct = (monthly_diff / monthly_baseline) * 100.0

    hard_stop_usd = abs(monthly_diff) > threshold_usd
    hard_stop_pct = pct is not None and abs(pct) > threshold_pct
    hard_stop = hard_stop_usd or hard_stop_pct

    breakdown = []
    for project in data.get("projects") or []:
        for resource in (project.get("diff") or {}).get("resources", [])[:30]:
            breakdown.append(
                {
                    "name": resource.get("name"),
                    "monthly_diff": _safe_float(resource.get("monthlyCost")),
                }
            )

    return {
        "currency": data.get("currency", "USD"),
        "monthly_diff": monthly_diff,
        "monthly_baseline": monthly_baseline,
        "monthly_after": monthly_after,
        "diff_percentage": pct,
        "thresholds": {
            "delta_usd": threshold_usd,
            "delta_pct": threshold_pct,
        },
        "hard_stop": hard_stop,
        "hard_stop_reason": (
            f"delta {monthly_diff:+.2f} USD excede ±{threshold_usd}"
            if hard_stop_usd
            else f"delta {pct:+.1f}% excede ±{threshold_pct}%"
            if hard_stop_pct
            else None
        ),
        "breakdown": breakdown,
        "command": _cmd_summary(result),
    }


def _safe_float(v: object | None) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _cmd_summary(result) -> dict:
    return {
        "cmd": "infracost diff",
        "exit_code": result.exit_code,
        "duration_ms": result.duration_ms,
        "truncated": result.truncated,
    }
