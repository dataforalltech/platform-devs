from __future__ import annotations

import os
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from .standards_tool import _grade, check_doc_standards
from .validation_tool import check_required_docs


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run_git_log_timestamp(file_path: Path, cwd: Path) -> int | None:
    """
    Runs git log to get last commit timestamp for a file.
    Returns Unix timestamp or None if git not available or file not tracked.
    """
    try:
        result = subprocess.run(
            ["git", "log", "--format=%ct", "-1", "--", str(file_path)],
            capture_output=True,
            text=True,
            cwd=str(cwd),
            timeout=10,
        )
        stdout = result.stdout.strip()
        if stdout:
            return int(stdout)
        return None
    except FileNotFoundError:
        return None
    except (subprocess.TimeoutExpired, ValueError):
        return None


def find_stale_docs(
    store: Any,
    settings: Any,
    *,
    repo_path: str,
    days_threshold: int | None = None,
) -> dict:
    """
    Detecta docs não atualizados há mais de X dias via `git log`.
    """
    if not repo_path:
        return {
            "error": "ValidationError",
            "details": "repo_path is required",
            "tool": "find_stale_docs",
        }

    root = Path(repo_path)
    if not root.exists():
        return {
            "error": "ValidationError",
            "details": f"repo_path not found: {repo_path}",
            "tool": "find_stale_docs",
        }

    threshold = days_threshold if days_threshold is not None else settings.stale_days_threshold
    now_ts = time.time()
    threshold_secs = threshold * 86400

    stale_docs: list[dict[str, Any]] = []
    total_docs = 0

    for pattern in ["**/*.md", "**/*.rst"]:
        for fpath in root.rglob(pattern.lstrip("*").lstrip("/")):
            if not fpath.is_file():
                continue
            if any(part.startswith(".") for part in fpath.parts):
                continue

            total_docs += 1

            # Try git log first
            git_ts = _run_git_log_timestamp(fpath, root)
            if git_ts is not None:
                last_ts = git_ts
                source = "git"
            else:
                # Fallback to mtime
                try:
                    last_ts = int(os.path.getmtime(str(fpath)))
                    source = "mtime"
                except OSError:
                    continue

            age_secs = now_ts - last_ts
            days_since = int(age_secs / 86400)

            if age_secs > threshold_secs:
                last_updated = datetime.fromtimestamp(last_ts, tz=UTC).isoformat()
                rel_path = str(fpath.relative_to(root)).replace("\\", "/")
                stale_docs.append(
                    {
                        "file": rel_path,
                        "last_updated": last_updated,
                        "days_since_update": days_since,
                        "source": source,
                    }
                )

    stale_docs.sort(key=lambda d: d["days_since_update"], reverse=True)

    return {
        "repo_path": repo_path,
        "threshold_days": threshold,
        "total_docs": total_docs,
        "stale_count": len(stale_docs),
        "stale_docs": stale_docs,
    }


def audit_repo(
    store: Any,
    settings: Any,
    *,
    repo_path: str,
    standard: str = "standard",
) -> dict:
    """
    Auditoria completa do repositório.
    """
    if not repo_path:
        return {
            "error": "ValidationError",
            "details": "repo_path is required",
            "tool": "audit_repo",
        }

    root = Path(repo_path)
    if not root.exists():
        return {
            "error": "ValidationError",
            "details": f"repo_path not found: {repo_path}",
            "tool": "audit_repo",
        }

    start_time = time.monotonic()

    # 1. Check required docs
    req_result = check_required_docs(store, settings, repo_path=repo_path, standard=standard)
    if "error" in req_result:
        return req_result

    completeness_pct = req_result.get("coverage_pct", 0.0)
    missing_required = len(req_result.get("missing", []))

    # 2. Check doc standards
    standards_result = check_doc_standards(store, settings, repo_path=repo_path, standard=standard)
    if "error" in standards_result:
        return standards_result

    standards_score = standards_result.get("overall_score", 0)

    # 3. Find stale docs
    stale_result = find_stale_docs(store, settings, repo_path=repo_path)
    if "error" in stale_result:
        stale_result = {"total_docs": 0, "stale_count": 0, "stale_docs": []}

    total_docs = stale_result.get("total_docs", 0)
    stale_count = stale_result.get("stale_count", 0)

    # 4. Freshness score
    if total_docs == 0:
        freshness_score = 100
    else:
        freshness_score = max(0, 100 - int(stale_count / total_docs * 100))

    # Weighted score
    overall_score = int(
        completeness_pct * 0.35
        + standards_score * 0.40
        + freshness_score * 0.25
    )
    grade = _grade(overall_score)

    # Build recommendations
    recommendations: list[str] = []
    if missing_required > 0:
        missing = req_result.get("missing", [])
        recommendations.append(f"Adicionar arquivos obrigatórios: {', '.join(missing)}")
    if standards_score < 80:
        for rec in standards_result.get("recommendations", [])[:3]:
            recommendations.append(rec)
    if stale_count > 0:
        stale_files = stale_result.get("stale_docs", [])
        if stale_files:
            worst = stale_files[0]
            recommendations.append(
                f"Atualizar {worst['file']} ({worst['days_since_update']} dias sem update)"
            )

    # Count total issues from standards
    total_issues = len(standards_result.get("issues", []))

    duration_ms = int((time.monotonic() - start_time) * 1000)

    summary = {
        "total_docs": total_docs,
        "stale_docs": stale_count,
        "missing_required": missing_required,
        "total_issues": total_issues,
    }
    details = {
        "required_docs": req_result,
        "standards": standards_result.get("categories", {}),
        "stale": stale_result.get("stale_docs", [])[:5],
    }

    audit_id = store.save_audit(
        repo_path=repo_path,
        score=overall_score,
        grade=grade,
        summary=summary,
        details=details,
        duration_ms=duration_ms,
    )

    return {
        "repo_path": repo_path,
        "audit_id": audit_id,
        "score": overall_score,
        "grade": grade,
        "categories": {
            "completeness": {"score": int(completeness_pct), "weight": 35},
            "standards": {"score": standards_score, "weight": 40},
            "freshness": {"score": freshness_score, "weight": 25},
        },
        "summary": summary,
        "recommendations": recommendations,
        "duration_ms": duration_ms,
    }


def get_audit_history(
    store: Any,
    settings: Any,
    *,
    repo_path: str | None = None,
    limit: int = 10,
) -> dict:
    """
    Retorna histórico de auditorias salvas no SQLite.
    """
    audits = store.list_audits(repo_path=repo_path, limit=limit)
    return {
        "total": len(audits),
        "audits": [
            {
                "id": a["id"],
                "repo_path": a["repo_path"],
                "started_at": a["started_at"],
                "score": a["score"],
                "grade": a["grade"],
                "summary": a["summary"],
            }
            for a in audits
        ],
    }


def generate_doc_report(
    store: Any,
    settings: Any,
    *,
    repo_path: str,
) -> dict:
    """
    Relatório final de qualidade documental.
    """
    if not repo_path:
        return {
            "error": "ValidationError",
            "details": "repo_path is required",
            "tool": "generate_doc_report",
        }

    # Get audit history
    audits = store.list_audits(repo_path=repo_path, limit=10)

    if not audits:
        # Run audit_repo if no history
        audit_result = audit_repo(store, settings, repo_path=repo_path)
        if "error" in audit_result:
            return audit_result
        audits = store.list_audits(repo_path=repo_path, limit=10)

    if not audits:
        return {
            "error": "ValidationError",
            "details": "Could not generate audit data",
            "tool": "generate_doc_report",
        }

    latest = audits[0]
    score = latest["score"]
    grade = latest["grade"]
    last_audit = latest["started_at"]

    # Determine trend
    trend = "no_history"
    if len(audits) >= 2:
        prev_score = audits[1]["score"]
        diff = score - prev_score
        if diff >= 5:
            trend = "improving"
        elif diff <= -5:
            trend = "declining"
        else:
            trend = "stable"
    elif len(audits) == 1:
        trend = "no_history"

    # Extract highlights from summary
    summary = latest.get("summary", {})
    total_docs = summary.get("total_docs", 0)
    stale_docs = summary.get("stale_docs", 0)
    missing_required = summary.get("missing_required", 0)
    total_issues = summary.get("total_issues", 0)

    # Build highlights
    if missing_required == 0 and total_docs > 0:
        best_highlight = f"Completude 100% — todos os {total_docs} docs obrigatórios presentes"
    elif total_issues == 0:
        best_highlight = "Sem problemas estruturais detectados nos documentos"
    else:
        best_highlight = f"Score geral: {score}/100 ({grade})"

    if stale_docs > 0:
        worst_highlight = (
            f"Freshness — {stale_docs} doc(s) com mais de "
            f"{settings.stale_days_threshold} dias sem update"
        )
    elif total_issues > 0:
        worst_highlight = f"{total_issues} issue(s) estrutural(is) nos documentos"
    else:
        worst_highlight = "Nenhum problema crítico identificado"

    # Build action items
    action_items: list[dict[str, str]] = []
    if missing_required > 0:
        action_items.append(
            {"priority": "high", "action": f"Adicionar {missing_required} arquivo(s) obrigatório(s)"}
        )
    if stale_docs > 0:
        action_items.append(
            {
                "priority": "medium" if stale_docs <= 2 else "high",
                "action": f"Atualizar {stale_docs} doc(s) desatualizado(s)",
            }
        )
    if total_issues > 0:
        action_items.append(
            {
                "priority": "medium",
                "action": f"Corrigir {total_issues} issue(s) de estrutura nos documentos",
            }
        )
    if score < 60:
        action_items.append(
            {
                "priority": "high",
                "action": "Realizar revisão completa da documentação (score abaixo de 60)",
            }
        )

    return {
        "repo_path": repo_path,
        "generated_at": _now(),
        "score": score,
        "grade": grade,
        "last_audit": last_audit,
        "trend": trend,
        "highlights": {
            "best": best_highlight,
            "worst": worst_highlight,
        },
        "action_items": action_items,
    }
