from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_coverage_report(
    store: Any,
    settings: Any,
    *,
    repo_path: str,
    framework: str = "auto",
) -> dict:
    """Lê relatório de cobertura: Python (coverage.json) ou Jest (coverage-summary.json)."""
    if not repo_path:
        return {
            "error": "ValidationError",
            "details": "repo_path is required",
            "tool": "get_coverage_report",
        }

    p = Path(repo_path)
    is_node = (p / "package.json").exists()
    actual_fw = framework if framework != "auto" else ("javascript" if is_node else "python")

    overall_pct = 0.0
    lines_covered = 0
    lines_total = 0
    modules: list[dict] = []

    if actual_fw in ("javascript", "typescript"):
        # Jest: coverage/coverage-summary.json
        summary_path = p / "coverage" / "coverage-summary.json"
        if summary_path.exists():
            try:
                data = json.loads(summary_path.read_text(encoding="utf-8"))
                total = data.get("total", {})
                lines_info = total.get("lines", {})
                overall_pct = lines_info.get("pct", 0.0)
                lines_covered = lines_info.get("covered", 0)
                lines_total = lines_info.get("total", 0)
                for fname, fdata in data.items():
                    if fname == "total":
                        continue
                    flines = fdata.get("lines", {})
                    modules.append(
                        {
                            "file": fname,
                            "coverage_pct": flines.get("pct", 0.0),
                        }
                    )
            except (json.JSONDecodeError, KeyError):
                pass
        else:
            return {
                "error": "coverage_not_found",
                "details": "Run jest with --coverage first",
                "tool": "get_coverage_report",
            }
    else:
        # Python: coverage.json
        cov_json = p / "coverage.json"
        if not cov_json.exists():
            # Try to generate
            try:
                subprocess.run(
                    ["python", "-m", "coverage", "json",
                     "--omit=*/test*,*/venv*", "-q"],
                    capture_output=True,
                    text=True,
                    cwd=repo_path,
                    timeout=settings.subprocess_timeout,
                )
            except (FileNotFoundError, subprocess.TimeoutExpired):
                pass

        if cov_json.exists():
            try:
                data = json.loads(cov_json.read_text(encoding="utf-8"))
                totals = data.get("totals", {})
                lines_covered = totals.get("covered_lines", 0)
                lines_total = totals.get("num_statements", 0)
                overall_pct = (
                    round(lines_covered / lines_total * 100, 2)
                    if lines_total > 0
                    else 0.0
                )
                for fname, fdata in (data.get("files") or {}).items():
                    fsum = fdata.get("summary", {})
                    flines_total = fsum.get("num_statements", 0)
                    flines_covered = fsum.get("covered_lines", 0)
                    fpct = (
                        round(flines_covered / flines_total * 100, 2)
                        if flines_total > 0
                        else 0.0
                    )
                    modules.append({"file": fname, "coverage_pct": fpct})
            except (json.JSONDecodeError, KeyError):
                pass
        else:
            return {
                "error": "coverage_not_found",
                "details": "Run pytest --cov first to generate coverage data",
                "tool": "get_coverage_report",
            }

    meets_threshold = overall_pct >= settings.coverage_threshold

    run_id = store.save_run(
        run_type="coverage",
        status="passed" if meets_threshold else "failed",
        summary={
            "overall_pct": overall_pct,
            "meets_threshold": meets_threshold,
        },
        details={"modules": modules[:20]},
        repo_path=repo_path,
        framework=actual_fw,
    )

    return {
        "framework": actual_fw,
        "overall_pct": overall_pct,
        "lines_covered": lines_covered,
        "lines_total": lines_total,
        "threshold_pct": settings.coverage_threshold,
        "meets_threshold": meets_threshold,
        "modules": modules,
        "run_id": run_id,
    }


def _compute_category_score(runs: list[dict], category: str) -> dict[str, Any]:
    """Computa score 0-100 e summary para uma categoria."""
    if not runs:
        return {"score": 0, "summary": "no data", "last_run": None}

    last = runs[0]
    status = last.get("status", "")
    summary = last.get("summary", {})
    started_at = last.get("started_at")

    if category == "unit":
        passed = summary.get("passed", 0)
        failed = summary.get("failed", 0)
        errors = summary.get("errors", 0)
        total = passed + failed + errors
        score = int(passed / total * 100) if total > 0 else 0
        desc = f"{passed}/{total} passed"
    elif category == "security":
        high = summary.get("high", 0)
        medium = summary.get("medium", 0)
        low = summary.get("low", 0)
        if high > 0:
            score = max(0, 50 - high * 10)
        elif medium > 0:
            score = max(0, 80 - medium * 7)
        else:
            score = max(0, 95 - low * 2)
        total = high + medium + low
        desc = (
            f"{high} high, {medium} medium, {low} low issues"
            if total > 0
            else "no issues"
        )
    elif category == "linter":
        errs = summary.get("errors", 0)
        warns = summary.get("warnings", 0)
        if errs == 0 and warns == 0:
            score = 100
            desc = "clean"
        else:
            score = max(0, 100 - errs * 5 - warns * 2)
            desc = f"{errs} errors, {warns} warnings"
    elif category == "coverage":
        pct = summary.get("overall_pct", 0.0)
        score = int(min(100, pct))
        desc = f"{pct:.1f}%"
    elif category == "dependencies":
        vulns = summary.get("vulnerabilities", 0)
        if vulns == 0:
            score = 100
            desc = "no vulnerabilities"
        else:
            score = max(0, 100 - vulns * 15)
            desc = f"{vulns} vulnerable package(s)"
    else:
        score = 100 if status == "passed" else 0
        desc = status

    return {"score": score, "summary": desc, "last_run": started_at}


def _grade(score: int) -> str:
    if score >= 90:
        return "A"
    if score >= 75:
        return "B"
    if score >= 60:
        return "C"
    if score >= 40:
        return "D"
    return "F"


def generate_qa_report(
    store: Any,
    settings: Any,
    *,
    repo_path: str,
    last_n_runs: int = 1,
) -> dict:
    """
    Agrega últimas execuções por tipo para o repo_path.
    Score ponderado: unit 30%, security 25%, linter 20%, coverage 15%, dependencies 10%.
    """
    if not repo_path:
        return {
            "error": "ValidationError",
            "details": "repo_path is required",
            "tool": "generate_qa_report",
        }

    weights = {
        "unit": 0.30,
        "security": 0.25,
        "linter": 0.20,
        "coverage": 0.15,
        "dependencies": 0.10,
    }
    run_type_map = {
        "unit": "unit",
        "security": "security",
        "linter": "linter",
        "coverage": "coverage",
        "dependencies": "dependencies",
    }

    categories: dict[str, dict] = {}
    overall_score = 0.0

    for cat, run_type in run_type_map.items():
        runs = store.list_runs(repo_path=repo_path, run_type=run_type, limit=last_n_runs)
        cat_data = _compute_category_score(runs, cat)
        categories[cat] = cat_data
        overall_score += cat_data["score"] * weights[cat]

    overall_int = int(round(overall_score))
    grade = _grade(overall_int)

    # Build recommendations
    recommendations: list[str] = []
    sec = categories.get("security", {})
    if sec.get("score", 100) < 80:
        recommendations.append(
            f"Fix security issues: {sec.get('summary', '')} (bandit/npm audit)"
        )
    dep = categories.get("dependencies", {})
    if dep.get("score", 100) < 80:
        recommendations.append(
            f"Update vulnerable dependencies: {dep.get('summary', '')}"
        )
    lint = categories.get("linter", {})
    if lint.get("score", 100) < 90:
        recommendations.append(
            f"Fix linter issues: {lint.get('summary', '')} (ruff/eslint)"
        )
    cov = categories.get("coverage", {})
    if cov.get("score", 100) < settings.coverage_threshold:
        recommendations.append(
            f"Improve test coverage: {cov.get('summary', '')} "
            f"(threshold: {settings.coverage_threshold:.0f}%)"
        )
    unit = categories.get("unit", {})
    if unit.get("score", 100) < 100:
        recommendations.append(
            f"Fix failing tests: {unit.get('summary', '')}"
        )

    run_id = store.save_run(
        run_type="qa_report",
        status="passed" if overall_int >= 75 else "failed",
        summary={"overall_score": overall_int, "grade": grade},
        details={"categories": categories},
        repo_path=repo_path,
    )

    return {
        "repo_path": repo_path,
        "generated_at": _now(),
        "overall_score": overall_int,
        "grade": grade,
        "categories": categories,
        "recommendations": recommendations,
        "run_id": run_id,
    }
