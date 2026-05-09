from __future__ import annotations

import os
import time
from unittest.mock import patch

from src.tools.audit_tool import (
    audit_repo,
    find_stale_docs,
    generate_doc_report,
    get_audit_history,
)

_README = (
    "# Test Service\n\n"
    "## Installation\n\nRun pip install.\n\n"
    "## Usage\n\nImport and use.\n"
) * 5

_CHANGELOG = (
    "# Changelog\n\n"
    "## [Unreleased]\n\n"
    "## [1.0.0] - 2026-01-01\n\n"
    "### Added\n- Initial\n"
)


def test_audit_repo_saves_to_store(store, settings, tmp_path):
    (tmp_path / "README.md").write_text(_README, encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text(_CHANGELOG, encoding="utf-8")

    audit_repo(store, settings, repo_path=str(tmp_path))

    history = get_audit_history(store, settings, repo_path=str(tmp_path))
    assert history["total"] == 1
    assert history["audits"][0]["repo_path"] == str(tmp_path)


def test_audit_repo_returns_score_and_grade(store, settings, tmp_path):
    (tmp_path / "README.md").write_text(_README, encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text(_CHANGELOG, encoding="utf-8")

    result = audit_repo(store, settings, repo_path=str(tmp_path))

    assert "score" in result
    assert "grade" in result
    assert "audit_id" in result
    assert 0 <= result["score"] <= 100
    assert result["grade"] in ("A", "B", "C", "D", "F")
    assert "categories" in result
    assert "summary" in result


def test_find_stale_docs_uses_mtime_when_no_git(store, settings, tmp_path):
    old_file = tmp_path / "old_doc.md"
    old_file.write_text("# Old\n\nContent\n", encoding="utf-8")

    # Set mtime to 200 days ago
    old_ts = time.time() - (200 * 86400)
    os.utime(str(old_file), (old_ts, old_ts))

    # Mock git to raise FileNotFoundError (git not available)
    with patch(
        "src.tools.audit_tool._run_git_log_timestamp",
        return_value=None,
    ):
        result = find_stale_docs(store, settings, repo_path=str(tmp_path), days_threshold=90)

    assert result["stale_count"] >= 1
    stale_file = result["stale_docs"][0]
    assert stale_file["days_since_update"] >= 190
    assert stale_file["source"] == "mtime"


def test_find_stale_docs_with_git(store, settings, tmp_path):
    doc = tmp_path / "README.md"
    doc.write_text("# README\n\nContent\n", encoding="utf-8")

    # Mock git log to return a timestamp 100 days ago
    old_ts = int(time.time()) - (100 * 86400)

    with patch(
        "src.tools.audit_tool._run_git_log_timestamp",
        return_value=old_ts,
    ):
        result = find_stale_docs(store, settings, repo_path=str(tmp_path), days_threshold=90)

    assert result["stale_count"] == 1
    assert result["stale_docs"][0]["source"] == "git"
    assert result["stale_docs"][0]["days_since_update"] >= 99


def test_find_stale_docs_not_stale(store, settings, tmp_path):
    doc = tmp_path / "README.md"
    doc.write_text("# README\n\nContent\n", encoding="utf-8")

    # Mock git log to return a timestamp 5 days ago (not stale)
    recent_ts = int(time.time()) - (5 * 86400)

    with patch(
        "src.tools.audit_tool._run_git_log_timestamp",
        return_value=recent_ts,
    ):
        result = find_stale_docs(store, settings, repo_path=str(tmp_path), days_threshold=90)

    assert result["stale_count"] == 0


def test_get_audit_history_empty(store, settings, tmp_path):
    result = get_audit_history(store, settings, repo_path=str(tmp_path))
    assert result["total"] == 0
    assert result["audits"] == []


def test_get_audit_history_returns_latest_first(store, settings, tmp_path):
    (tmp_path / "README.md").write_text(_README, encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text(_CHANGELOG, encoding="utf-8")

    audit_repo(store, settings, repo_path=str(tmp_path))
    audit_repo(store, settings, repo_path=str(tmp_path))

    history = get_audit_history(store, settings, repo_path=str(tmp_path))
    assert history["total"] == 2
    # Should be ordered latest first
    assert history["audits"][0]["id"] > history["audits"][1]["id"]


def test_generate_doc_report_no_history(store, settings, tmp_path):
    (tmp_path / "README.md").write_text(_README, encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text(_CHANGELOG, encoding="utf-8")

    # No audit history yet → should run audit_repo first
    result = generate_doc_report(store, settings, repo_path=str(tmp_path))

    assert "score" in result
    assert "grade" in result
    assert "trend" in result
    assert result["trend"] == "no_history"
    assert "highlights" in result
    assert "action_items" in result


def test_generate_doc_report_trend_improving(store, settings, tmp_path):
    (tmp_path / "README.md").write_text(_README, encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text(_CHANGELOG, encoding="utf-8")

    # Audits are returned newest-first; save the older (low score) first,
    # then the newer (high score) — so audits[0].score=80, audits[1].score=50 → improving.
    store.save_audit(
        repo_path=str(tmp_path),
        score=50,
        grade="D",
        summary={"total_docs": 2, "stale_docs": 0, "missing_required": 0, "total_issues": 5},
        details={},
    )
    store.save_audit(
        repo_path=str(tmp_path),
        score=80,
        grade="B",
        summary={"total_docs": 2, "stale_docs": 0, "missing_required": 0, "total_issues": 1},
        details={},
    )

    # Verify ordering: newest first
    history = store.list_audits(repo_path=str(tmp_path), limit=2)
    assert history[0]["score"] == 80  # latest
    assert history[1]["score"] == 50  # previous

    result = generate_doc_report(store, settings, repo_path=str(tmp_path))
    # latest(80) > previous(50) by >=5 → improving
    assert result["trend"] == "improving"
