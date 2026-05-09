"""Testes das tools terraform — subprocess mockado via monkeypatch."""

from __future__ import annotations

import json

from src.tools import terraform_tool
from src.utils.subprocess_runner import BinaryNotFound, CommandResult


def _mock_result(stdout: str = "", stderr: str = "", exit_code: int = 0) -> CommandResult:
    return CommandResult(
        cmd=["fake"],
        cwd="/fake",
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        duration_ms=10,
        truncated=False,
    )


# --------------------------- terraform_validate --------------------------- #
def test_validate_returns_valid_true_for_clean_module(monkeypatch, fake_settings):
    output = json.dumps({"valid": True, "error_count": 0, "warning_count": 0, "diagnostics": []})
    monkeypatch.setattr(
        terraform_tool,
        "run_command",
        lambda *a, **kw: _mock_result(stdout=output),
    )
    res = terraform_tool.terraform_validate(fake_settings)
    assert res["valid"] is True
    assert res["error_count"] == 0
    assert res["command"]["exit_code"] == 0


def test_validate_surfaces_diagnostics(monkeypatch, fake_settings):
    output = json.dumps(
        {
            "valid": False,
            "error_count": 1,
            "warning_count": 0,
            "diagnostics": [{"severity": "error", "summary": "missing required argument"}],
        }
    )
    monkeypatch.setattr(
        terraform_tool, "run_command", lambda *a, **kw: _mock_result(stdout=output)
    )
    res = terraform_tool.terraform_validate(fake_settings)
    assert res["valid"] is False
    assert res["error_count"] == 1
    assert res["diagnostics"][0]["severity"] == "error"


def test_validate_handles_non_json_output(monkeypatch, fake_settings):
    monkeypatch.setattr(
        terraform_tool,
        "run_command",
        lambda *a, **kw: _mock_result(stdout="terraform not initialized", exit_code=1),
    )
    res = terraform_tool.terraform_validate(fake_settings)
    assert res["valid"] is False
    assert "raw_stdout" in res
    assert any("init" in n for n in res["notes"])


def test_validate_returns_binary_not_found(monkeypatch, fake_settings):
    def fake_run(*a, **kw):
        raise BinaryNotFound("fake-terraform-bin not on PATH")

    monkeypatch.setattr(terraform_tool, "run_command", fake_run)
    res = terraform_tool.terraform_validate(fake_settings)
    assert res["error"] == "binary_not_found"


# --------------------------- terraform_fmt_check --------------------------- #
def test_fmt_check_clean(monkeypatch, fake_settings):
    monkeypatch.setattr(
        terraform_tool, "run_command", lambda *a, **kw: _mock_result(exit_code=0)
    )
    res = terraform_tool.terraform_fmt_check(fake_settings)
    assert res["is_formatted"] is True
    assert res["files_needing_format"] == []


def test_fmt_check_with_diff(monkeypatch, fake_settings):
    output = "modules/foo/main.tf\n@@ -1,3 +1,3 @@\n-bad\n+good"
    monkeypatch.setattr(
        terraform_tool, "run_command", lambda *a, **kw: _mock_result(stdout=output, exit_code=3)
    )
    res = terraform_tool.terraform_fmt_check(fake_settings)
    assert res["is_formatted"] is False
    assert "modules/foo/main.tf" in res["files_needing_format"]
    assert "diff" in res


# --------------------------- terraform_plan --------------------------- #
def test_plan_no_changes(monkeypatch, fake_settings):
    monkeypatch.setattr(
        terraform_tool,
        "run_command",
        lambda *a, **kw: _mock_result(stdout="No changes. Your infrastructure matches.", exit_code=0),
    )
    res = terraform_tool.terraform_plan(fake_settings)
    assert res["has_changes"] is False
    assert res["add"] == 0
    assert res["plan_path"] is None


def test_plan_with_changes(monkeypatch, fake_settings):
    out = "Plan: 3 to add, 1 to change, 0 to destroy.\n"
    monkeypatch.setattr(
        terraform_tool, "run_command", lambda *a, **kw: _mock_result(stdout=out, exit_code=2)
    )
    res = terraform_tool.terraform_plan(fake_settings)
    assert res["has_changes"] is True
    assert res["add"] == 3
    assert res["change"] == 1
    assert res["destroy"] == 0
    assert res["plan_path"] is not None


def test_plan_failure(monkeypatch, fake_settings):
    monkeypatch.setattr(
        terraform_tool,
        "run_command",
        lambda *a, **kw: _mock_result(stderr="Error: invalid", exit_code=1),
    )
    res = terraform_tool.terraform_plan(fake_settings)
    assert res["error"] == "plan_failed"


# --------------------------- terraform_show_plan --------------------------- #
def test_show_plan_missing_file(fake_settings, tmp_path):
    res = terraform_tool.terraform_show_plan(
        fake_settings, plan_path=str(tmp_path / "nonexistent.tfplan")
    )
    assert res["error"] == "plan_not_found"


def test_show_plan_parses_json(monkeypatch, fake_settings, tmp_path):
    plan_file = tmp_path / "fake.tfplan"
    plan_file.write_text("binary placeholder")
    output = json.dumps(
        {
            "format_version": "1.2",
            "terraform_version": "1.5.0",
            "resource_changes": [
                {"address": "aws_s3_bucket.x", "type": "aws_s3_bucket", "change": {"actions": ["create"]}},
                {"address": "aws_s3_bucket.y", "type": "aws_s3_bucket", "change": {"actions": ["update"]}},
            ],
        }
    )
    monkeypatch.setattr(
        terraform_tool, "run_command", lambda *a, **kw: _mock_result(stdout=output)
    )
    res = terraform_tool.terraform_show_plan(fake_settings, plan_path=str(plan_file))
    assert res["resource_changes_count"] == 2
    assert res["changes_by_action"]["create"] == 1
    assert res["changes_by_action"]["update"] == 1


# --------------------------- resolve_root --------------------------- #
def test_plan_requires_path_or_root(monkeypatch):
    """Settings sem terraform_root e sem path explícito → erro tipado."""
    from src.config.settings import Settings

    bare = Settings(terraform_root=None, terraform_bin="x")
    res = terraform_tool.terraform_plan(bare)
    assert res["error"] == "validation_error"
