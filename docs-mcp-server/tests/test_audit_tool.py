"""audit_tool: `audit_repo`/`get_audit_history`/`generate_doc_report` persistem no
store (async → MySQL real, integration); `find_stale_docs` e `_run_git_log_timestamp`
são compute-only (herméticos)."""

from __future__ import annotations

import os
import subprocess
import time
from unittest.mock import MagicMock, patch

import pytest

from src.tools.audit_tool import (
    _run_git_log_timestamp,
    audit_repo,
    find_stale_docs,
    generate_doc_report,
    get_audit_history,
)

from .conftest import requires_mysql

_README = ("# Test Service\n\n## Installation\n\nRun pip install.\n\n## Usage\n\nImport and use.\n") * 5

_CHANGELOG = "# Changelog\n\n## [Unreleased]\n\n## [1.0.0] - 2026-01-01\n\n### Added\n- Initial\n"


# ── audit_repo / histórico (toca o store → MySQL real) ─────────────────────────
@pytest.mark.integration
@requires_mysql
async def test_audit_repo_saves_to_store(store_a, settings, tmp_path):
    (tmp_path / "README.md").write_text(_README, encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text(_CHANGELOG, encoding="utf-8")

    await audit_repo(store_a, settings, repo_path=str(tmp_path))

    history = await get_audit_history(store_a, settings, repo_path=str(tmp_path))
    assert history["total"] == 1
    assert history["audits"][0]["repo_path"] == str(tmp_path)


@pytest.mark.integration
@requires_mysql
async def test_audit_repo_returns_score_and_grade(store_a, settings, tmp_path):
    (tmp_path / "README.md").write_text(_README, encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text(_CHANGELOG, encoding="utf-8")

    result = await audit_repo(store_a, settings, repo_path=str(tmp_path))

    assert "score" in result
    assert "grade" in result
    assert "audit_id" in result
    assert 0 <= result["score"] <= 100
    assert result["grade"] in ("A", "B", "C", "D", "F")
    assert "categories" in result
    assert "summary" in result


@pytest.mark.integration
@requires_mysql
async def test_get_audit_history_empty(store_a, settings, tmp_path):
    result = await get_audit_history(store_a, settings, repo_path=str(tmp_path))
    assert result["total"] == 0
    assert result["audits"] == []


@pytest.mark.integration
@requires_mysql
async def test_get_audit_history_returns_latest_first(store_a, settings, tmp_path):
    (tmp_path / "README.md").write_text(_README, encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text(_CHANGELOG, encoding="utf-8")

    await audit_repo(store_a, settings, repo_path=str(tmp_path))
    await audit_repo(store_a, settings, repo_path=str(tmp_path))

    history = await get_audit_history(store_a, settings, repo_path=str(tmp_path))
    assert history["total"] == 2
    # Should be ordered latest first
    assert history["audits"][0]["id"] > history["audits"][1]["id"]


@pytest.mark.integration
@requires_mysql
async def test_generate_doc_report_no_history(store_a, settings, tmp_path):
    (tmp_path / "README.md").write_text(_README, encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text(_CHANGELOG, encoding="utf-8")

    # No audit history yet → should run audit_repo first
    result = await generate_doc_report(store_a, settings, repo_path=str(tmp_path))

    assert "score" in result
    assert "grade" in result
    assert "trend" in result
    assert result["trend"] == "no_history"
    assert "highlights" in result
    assert "action_items" in result


@pytest.mark.integration
@requires_mysql
async def test_generate_doc_report_trend_improving(store_a, settings, tmp_path):
    # Audits are returned newest-first; save the older (low score) first,
    # then the newer (high score) — so audits[0].score=80, audits[1].score=50 → improving.
    await store_a.save_audit(
        repo_path=str(tmp_path),
        score=50,
        grade="D",
        summary={"total_docs": 2, "stale_docs": 0, "missing_required": 0, "total_issues": 5},
        details={},
    )
    await store_a.save_audit(
        repo_path=str(tmp_path),
        score=80,
        grade="B",
        summary={"total_docs": 2, "stale_docs": 0, "missing_required": 0, "total_issues": 1},
        details={},
    )

    # Verify ordering: newest first
    history = await store_a.list_audits(repo_path=str(tmp_path), limit=2)
    assert history[0]["score"] == 80  # latest
    assert history[1]["score"] == 50  # previous

    result = await generate_doc_report(store_a, settings, repo_path=str(tmp_path))
    # latest(80) > previous(50) by >=5 → improving
    assert result["trend"] == "improving"


@pytest.mark.integration
@requires_mysql
async def test_audit_repo_recommendations_for_missing_and_stale(store_a, settings, tmp_path):
    # Only an old README → missing CHANGELOG (full standard) and stale doc.
    readme = ("# Svc\n\n## Installation\n\nInstall.\n\n## Usage\n\nUse.\n") * 6
    old = tmp_path / "README.md"
    old.write_text(readme, encoding="utf-8")
    old_ts = time.time() - (200 * 86400)
    os.utime(str(old), (old_ts, old_ts))

    with patch("src.tools.audit_tool._run_git_log_timestamp", return_value=None):
        result = await audit_repo(store_a, settings, repo_path=str(tmp_path), standard="full")

    recs = " ".join(result["recommendations"])
    assert "obrigatórios" in recs  # missing CHANGELOG/AGENTS
    assert result["summary"]["stale_docs"] >= 1
    assert any("dias sem update" in r for r in result["recommendations"])


@pytest.mark.integration
@requires_mysql
async def test_generate_doc_report_action_items_high_priority(store_a, settings, tmp_path):
    # Seed a low-score audit with missing required + stale docs + issues.
    await store_a.save_audit(
        repo_path=str(tmp_path),
        score=30,
        grade="F",
        summary={"total_docs": 5, "stale_docs": 4, "missing_required": 2, "total_issues": 7},
        details={},
    )
    result = await generate_doc_report(store_a, settings, repo_path=str(tmp_path))

    priorities = {a["priority"] for a in result["action_items"]}
    actions = " ".join(a["action"] for a in result["action_items"])
    assert "high" in priorities
    assert "obrigatório" in actions
    assert result["highlights"]["worst"]  # freshness worst path
    assert result["trend"] == "no_history"


# ── find_stale_docs (compute-only, filesystem/git → hermético) ────────────────
def test_find_stale_docs_uses_mtime_when_no_git(settings, tmp_path):
    old_file = tmp_path / "old_doc.md"
    old_file.write_text("# Old\n\nContent\n", encoding="utf-8")

    # Set mtime to 200 days ago
    old_ts = time.time() - (200 * 86400)
    os.utime(str(old_file), (old_ts, old_ts))

    # Mock git to return None (git not available / file untracked)
    with patch("src.tools.audit_tool._run_git_log_timestamp", return_value=None):
        result = find_stale_docs(None, settings, repo_path=str(tmp_path), days_threshold=90)

    assert result["stale_count"] >= 1
    stale_file = result["stale_docs"][0]
    assert stale_file["days_since_update"] >= 190
    assert stale_file["source"] == "mtime"


def test_find_stale_docs_with_git(settings, tmp_path):
    doc = tmp_path / "README.md"
    doc.write_text("# README\n\nContent\n", encoding="utf-8")

    # Mock git log to return a timestamp 100 days ago
    old_ts = int(time.time()) - (100 * 86400)

    with patch("src.tools.audit_tool._run_git_log_timestamp", return_value=old_ts):
        result = find_stale_docs(None, settings, repo_path=str(tmp_path), days_threshold=90)

    assert result["stale_count"] == 1
    assert result["stale_docs"][0]["source"] == "git"
    assert result["stale_docs"][0]["days_since_update"] >= 99


def test_find_stale_docs_not_stale(settings, tmp_path):
    doc = tmp_path / "README.md"
    doc.write_text("# README\n\nContent\n", encoding="utf-8")

    # Mock git log to return a timestamp 5 days ago (not stale)
    recent_ts = int(time.time()) - (5 * 86400)

    with patch("src.tools.audit_tool._run_git_log_timestamp", return_value=recent_ts):
        result = find_stale_docs(None, settings, repo_path=str(tmp_path), days_threshold=90)

    assert result["stale_count"] == 0


def test_find_stale_docs_missing_repo_path(settings):
    result = find_stale_docs(None, settings, repo_path="")
    assert result["error"] == "ValidationError"


def test_find_stale_docs_nonexistent_repo(settings):
    result = find_stale_docs(None, settings, repo_path="/nope/xyz")
    assert result["error"] == "ValidationError"


# ── _run_git_log_timestamp (subprocess mockado) ───────────────────────────────
def test_run_git_log_timestamp_parses_stdout(tmp_path):
    proc = MagicMock()
    proc.stdout = "1700000000\n"
    with patch("src.tools.audit_tool.subprocess.run", return_value=proc) as run:
        ts = _run_git_log_timestamp(tmp_path / "README.md", tmp_path)
    assert ts == 1700000000
    run.assert_called_once()


def test_run_git_log_timestamp_empty_stdout(tmp_path):
    proc = MagicMock()
    proc.stdout = "\n"
    with patch("src.tools.audit_tool.subprocess.run", return_value=proc):
        ts = _run_git_log_timestamp(tmp_path / "README.md", tmp_path)
    assert ts is None


def test_run_git_log_timestamp_git_missing(tmp_path):
    with patch("src.tools.audit_tool.subprocess.run", side_effect=FileNotFoundError):
        ts = _run_git_log_timestamp(tmp_path / "README.md", tmp_path)
    assert ts is None


def test_run_git_log_timestamp_timeout(tmp_path):
    with patch(
        "src.tools.audit_tool.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="git", timeout=10),
    ):
        ts = _run_git_log_timestamp(tmp_path / "README.md", tmp_path)
    assert ts is None
