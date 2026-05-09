"""Testes do runner central — não depende de CLIs reais."""

from __future__ import annotations

import pytest

from src.utils.subprocess_runner import (
    BinaryNotFound,
    CommandTimeout,
    _redact,
    _truncate,
    run_command,
)


def test_redact_masks_token():
    line = 'export TOKEN=abcdef1234567890'
    out = _redact(line)
    assert "abcdef1234567890" not in out
    assert "***" in out


def test_redact_masks_password_and_secret():
    assert "***" in _redact('password="hunter2"')
    assert "***" in _redact('secret: shhh')
    assert "***" in _redact('api_key=sk-real-token')


def test_redact_does_not_touch_safe_lines():
    line = "Plan: 3 to add, 1 to change, 0 to destroy."
    assert _redact(line) == line


def test_truncate_below_limit_returns_unchanged():
    text = "abc"
    out, truncated = _truncate(text, 100)
    assert out == "abc"
    assert truncated is False


def test_truncate_above_limit_appends_marker():
    text = "x" * 200
    out, truncated = _truncate(text, 50)
    assert truncated is True
    assert "truncated" in out
    assert len(out) <= 50 + 30


def test_run_command_raises_for_missing_binary():
    with pytest.raises(BinaryNotFound):
        run_command(
            ["this-binary-definitely-does-not-exist-xyz"],
            timeout=5,
            output_max_chars=1000,
        )


def test_run_command_captures_output(tmp_path):
    """Roda um echo via Python (sempre disponível)."""
    import sys

    result = run_command(
        [sys.executable, "-c", "print('hello world')"],
        cwd=tmp_path,
        timeout=10,
        output_max_chars=4000,
    )
    assert result.exit_code == 0
    assert "hello world" in result.stdout
    assert result.duration_ms >= 0


def test_run_command_captures_nonzero_exit(tmp_path):
    import sys

    result = run_command(
        [sys.executable, "-c", "import sys; sys.exit(7)"],
        cwd=tmp_path,
        timeout=10,
        output_max_chars=4000,
    )
    assert result.exit_code == 7


def test_run_command_timeout(tmp_path):
    import sys

    with pytest.raises(CommandTimeout):
        run_command(
            [sys.executable, "-c", "import time; time.sleep(10)"],
            cwd=tmp_path,
            timeout=1,
            output_max_chars=1000,
        )


def test_run_command_truncates_huge_output(tmp_path):
    import sys

    result = run_command(
        [sys.executable, "-c", "print('x' * 50000)"],
        cwd=tmp_path,
        timeout=10,
        output_max_chars=1000,
    )
    assert result.truncated is True
    assert len(result.stdout) <= 1100


def test_run_command_rejects_empty_cmd():
    with pytest.raises(ValueError):
        run_command([], timeout=5, output_max_chars=1000)
