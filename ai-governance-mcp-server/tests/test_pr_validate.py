"""Testes do scripts/pr_validate.py.

Foco nas funções puras: _format_comment (markdown rendering matrix),
_post_comment (sob mock), e fluxo de payload (--dry-run).
"""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import pr_validate as pr  # noqa: E402


# --------------------------- _format_comment matrix --------------------------- #
def test_format_comment_critical_marks_blocked():
    payload = {"affected_files": ["a.py"], "affected_layers": ["backend"]}
    result = {
        "approved": False,
        "risk_level": "critical",
        "violations": ["Fallback silencioso"],
        "required_actions": ["Adicione log.warning"],
        "recommendations": [],
        "notes": [],
    }
    md = pr._format_comment(payload, result)
    assert "BLOCKED" in md
    assert "🛑" in md
    assert "critical" in md
    assert "Fallback silencioso" in md
    assert "Adicione log.warning" in md


def test_format_comment_high_marks_high_risk():
    payload = {"affected_files": [], "affected_layers": []}
    result = {
        "approved": True,
        "risk_level": "high",
        "violations": [],
        "required_actions": [],
        "recommendations": ["Documente as deps"],
        "notes": [],
    }
    md = pr._format_comment(payload, result)
    assert "HIGH RISK" in md
    assert "Documente as deps" in md


def test_format_comment_medium_renders_warning():
    payload = {"affected_files": ["a"], "affected_layers": ["backend"]}
    result = {
        "approved": True,
        "risk_level": "medium",
        "violations": [],
        "required_actions": [],
        "recommendations": [],
        "notes": ["PR grande"],
    }
    md = pr._format_comment(payload, result)
    assert "Medium" in md
    assert "PR grande" in md


def test_format_comment_low_marks_ok():
    payload = {"affected_files": ["a"], "affected_layers": []}
    result = {
        "approved": True,
        "risk_level": "low",
        "violations": [],
        "required_actions": [],
        "recommendations": [],
        "notes": [],
    }
    md = pr._format_comment(payload, result)
    assert "✅" in md
    assert "**OK**" in md


def test_format_comment_includes_file_count():
    payload = {"affected_files": ["a.py", "b.py", "c.py"], "affected_layers": ["backend", "testing"]}
    result = {
        "approved": True, "risk_level": "low",
        "violations": [], "required_actions": [], "recommendations": [], "notes": [],
    }
    md = pr._format_comment(payload, result)
    assert "3" in md
    assert "backend" in md and "testing" in md


def test_format_comment_handles_empty_layers():
    payload = {"affected_files": ["a"], "affected_layers": []}
    result = {
        "approved": True, "risk_level": "low",
        "violations": [], "required_actions": [], "recommendations": [], "notes": [],
    }
    md = pr._format_comment(payload, result)
    assert "(none detected)" in md


def test_format_comment_omits_empty_sections():
    """Sem violations/actions/recs/notes — não devem aparecer headers."""
    payload = {"affected_files": ["a"], "affected_layers": []}
    result = {
        "approved": True, "risk_level": "low",
        "violations": [], "required_actions": [], "recommendations": [], "notes": [],
    }
    md = pr._format_comment(payload, result)
    assert "### Violations" not in md
    assert "### Required actions" not in md
    assert "### Recommendations" not in md
    assert "### Notes" not in md


# --------------------------- _post_comment --------------------------- #
def test_post_comment_skips_without_pr_number(monkeypatch, capsys):
    monkeypatch.delenv("PR_NUMBER", raising=False)
    monkeypatch.delenv("GITHUB_REF", raising=False)
    ok = pr._post_comment("body", pr_number=None)
    assert ok is False
    err = capsys.readouterr().err
    assert "PR_NUMBER" in err


def test_post_comment_extracts_from_github_ref(monkeypatch):
    """GITHUB_REF=refs/pull/42/merge → PR=42."""
    monkeypatch.delenv("PR_NUMBER", raising=False)
    monkeypatch.setenv("GITHUB_REF", "refs/pull/42/merge")

    captured = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        class Result:
            returncode = 0
            stderr = ""
        return Result()

    monkeypatch.setattr(pr.subprocess, "run", fake_run)
    ok = pr._post_comment("body")
    assert ok is True
    assert "42" in captured["args"]


def test_post_comment_handles_gh_missing(monkeypatch, capsys):
    monkeypatch.setenv("PR_NUMBER", "42")

    def fake_run(args, **kwargs):
        raise FileNotFoundError("gh")

    monkeypatch.setattr(pr.subprocess, "run", fake_run)
    ok = pr._post_comment("body")
    assert ok is False
    assert "gh CLI não encontrada" in capsys.readouterr().err


# --------------------------- diff helpers --------------------------- #
def test_diff_range_truncates(monkeypatch):
    big = "x" * (pr.core._MAX_DIFF_CHARS + 1000)
    monkeypatch.setattr(pr, "_git", lambda args: big)
    out = pr._diff_range("base", "head")
    assert "truncated" in out
    assert len(out) <= pr.core._MAX_DIFF_CHARS + 50


def test_files_changed_returns_list(monkeypatch):
    monkeypatch.setattr(
        pr, "_git", lambda args: "a.py\nb.py\n   \n  c.py  \n"
    )
    files = pr._files_changed("base", "head")
    assert files == ["a.py", "b.py", "c.py"]


def test_commit_messages_joins_subjects(monkeypatch):
    monkeypatch.setattr(pr, "_git", lambda args: "feat: a\nfix: b\nchore: c\n")
    msgs = pr._commit_messages("base", "head")
    assert "feat: a" in msgs
    assert "fix: b" in msgs
    assert " | " in msgs


def test_commit_messages_caps_at_10(monkeypatch):
    long_log = "\n".join(f"feat: commit-{i}" for i in range(20))
    monkeypatch.setattr(pr, "_git", lambda args: long_log)
    msgs = pr._commit_messages("base", "head")
    assert msgs.count("|") <= 10  # 10 entries → no more than 9 separators
