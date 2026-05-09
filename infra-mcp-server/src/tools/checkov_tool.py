"""policy_scan_checkov: roda checkov sobre código terraform e devolve findings."""

from __future__ import annotations

import json

from ..config.settings import Settings
from ..utils.subprocess_runner import (
    BinaryNotFound,
    CommandTimeout,
    run_command,
)
from ..utils.validators import normalize_path


def policy_scan_checkov(
    settings: Settings,
    path: str,
    framework: str = "terraform",
    skip_checks: list[str] | None = None,
) -> dict:
    """Roda `checkov -d <path> -o json` e parseia.

    Args:
        path: diretório com .tf
        framework: terraform | terraform_plan | kubernetes | dockerfile (passa direto pra checkov)
        skip_checks: lista de check_ids para ignorar (mapeado para --skip-check CKV_AZ_X,...)

    Retorna findings agrupados por severity + counts.
    """
    try:
        target = normalize_path(path, "path")
    except ValueError as e:
        return {"error": "validation_error", "details": str(e), "tool": "policy_scan_checkov"}

    if framework not in {"terraform", "terraform_plan", "kubernetes", "dockerfile", "all"}:
        return {
            "error": "validation_error",
            "details": f"framework inválido: {framework!r}",
            "tool": "policy_scan_checkov",
        }

    cmd = [
        settings.checkov_bin,
        "-d",
        str(target),
        "-o",
        "json",
        "--framework",
        framework,
        "--quiet",
        "--soft-fail",  # não retornamos exit != 0; agente decide pelo conteúdo
    ]
    if skip_checks:
        cmd += ["--skip-check", ",".join(skip_checks)]

    try:
        result = run_command(
            cmd,
            cwd=target.parent if target.is_file() else target,
            timeout=settings.scan_timeout,
            output_max_chars=settings.output_max_chars,
        )
    except (BinaryNotFound, CommandTimeout) as e:
        if isinstance(e, BinaryNotFound):
            return {"error": "binary_not_found", "details": str(e), "tool": "policy_scan_checkov"}
        return {"error": "timeout", "details": str(e), "tool": "policy_scan_checkov"}

    # Checkov com --quiet --soft-fail emite JSON em stdout, mesmo sem findings.
    if not result.stdout.strip():
        return {
            "error": "empty_output",
            "details": result.stderr or "checkov não produziu output JSON",
            "tool": "policy_scan_checkov",
            "command": _cmd_summary(result),
        }

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        return {
            "error": "invalid_json",
            "details": str(e),
            "stdout_preview": result.stdout[:1000],
            "tool": "policy_scan_checkov",
            "command": _cmd_summary(result),
        }

    # Checkov pode retornar dict (single framework) ou list (--framework all).
    if isinstance(data, list):
        all_failed: list[dict] = []
        all_passed_count = 0
        for entry in data:
            results_section = entry.get("results", {}) if isinstance(entry, dict) else {}
            all_failed.extend(results_section.get("failed_checks", []))
            all_passed_count += len(results_section.get("passed_checks", []))
        failed = all_failed
        passed_count = all_passed_count
    else:
        results = data.get("results", {})
        failed = results.get("failed_checks", [])
        passed_count = len(results.get("passed_checks", []))

    by_severity: dict[str, int] = {}
    findings: list[dict] = []
    for f in failed:
        sev = (f.get("severity") or "MEDIUM").upper()
        by_severity[sev] = by_severity.get(sev, 0) + 1
        findings.append(
            {
                "check_id": f.get("check_id"),
                "severity": sev,
                "resource": f.get("resource"),
                "file_path": f.get("file_path"),
                "file_line_range": f.get("file_line_range", []),
                "description": f.get("check_name") or f.get("description"),
                "guideline": f.get("guideline"),
            }
        )

    has_critical_or_high = any(by_severity.get(s, 0) > 0 for s in ("CRITICAL", "HIGH"))

    return {
        "framework": framework,
        "passed_count": passed_count,
        "failed_count": len(failed),
        "by_severity": by_severity,
        "has_critical_or_high": has_critical_or_high,
        "hard_stop": has_critical_or_high,  # cicd-deploy.md §4 #3
        "findings": findings[:100],  # limite
        "command": _cmd_summary(result),
    }


def _cmd_summary(result) -> dict:
    return {
        "cmd": "checkov",
        "exit_code": result.exit_code,
        "duration_ms": result.duration_ms,
        "truncated": result.truncated,
    }
