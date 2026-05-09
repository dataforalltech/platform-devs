"""Testes do policy_scan_checkov."""

from __future__ import annotations

import json

from src.tools import checkov_tool
from src.utils.subprocess_runner import CommandResult


def _mock_result(stdout: str = "", stderr: str = "", exit_code: int = 0) -> CommandResult:
    return CommandResult(
        cmd=["fake"], cwd="/fake", exit_code=exit_code,
        stdout=stdout, stderr=stderr, duration_ms=10, truncated=False,
    )


def test_checkov_no_findings(monkeypatch, fake_settings, tmp_path):
    output = json.dumps(
        {"results": {"failed_checks": [], "passed_checks": [{"check_id": "CKV_AZ_1"}]}}
    )
    monkeypatch.setattr(checkov_tool, "run_command", lambda *a, **kw: _mock_result(stdout=output))
    res = checkov_tool.policy_scan_checkov(fake_settings, path=str(tmp_path))
    assert res["failed_count"] == 0
    assert res["passed_count"] == 1
    assert res["hard_stop"] is False


def test_checkov_high_severity_triggers_hard_stop(monkeypatch, fake_settings, tmp_path):
    output = json.dumps(
        {
            "results": {
                "failed_checks": [
                    {
                        "check_id": "CKV_AZ_1",
                        "severity": "HIGH",
                        "resource": "azurerm_storage_account.x",
                        "file_path": "main.tf",
                        "file_line_range": [10, 15],
                        "check_name": "Storage account should require HTTPS",
                    }
                ],
                "passed_checks": [],
            }
        }
    )
    monkeypatch.setattr(checkov_tool, "run_command", lambda *a, **kw: _mock_result(stdout=output))
    res = checkov_tool.policy_scan_checkov(fake_settings, path=str(tmp_path))
    assert res["failed_count"] == 1
    assert res["by_severity"]["HIGH"] == 1
    assert res["has_critical_or_high"] is True
    assert res["hard_stop"] is True


def test_checkov_medium_only_does_not_trigger_hard_stop(monkeypatch, fake_settings, tmp_path):
    output = json.dumps(
        {
            "results": {
                "failed_checks": [
                    {"check_id": "X", "severity": "MEDIUM", "resource": "r", "file_path": "f"},
                ],
                "passed_checks": [],
            }
        }
    )
    monkeypatch.setattr(checkov_tool, "run_command", lambda *a, **kw: _mock_result(stdout=output))
    res = checkov_tool.policy_scan_checkov(fake_settings, path=str(tmp_path))
    assert res["hard_stop"] is False


def test_checkov_handles_list_output_for_all_framework(monkeypatch, fake_settings, tmp_path):
    output = json.dumps(
        [
            {"results": {"failed_checks": [{"check_id": "X", "severity": "CRITICAL", "resource": "r"}], "passed_checks": []}},
            {"results": {"failed_checks": [], "passed_checks": [{"check_id": "Y"}]}},
        ]
    )
    monkeypatch.setattr(checkov_tool, "run_command", lambda *a, **kw: _mock_result(stdout=output))
    res = checkov_tool.policy_scan_checkov(fake_settings, path=str(tmp_path), framework="all")
    assert res["failed_count"] == 1
    assert res["by_severity"]["CRITICAL"] == 1
    assert res["hard_stop"] is True


def test_checkov_invalid_framework(fake_settings, tmp_path):
    res = checkov_tool.policy_scan_checkov(
        fake_settings, path=str(tmp_path), framework="rust"
    )
    assert res["error"] == "validation_error"


def test_checkov_empty_path(fake_settings):
    res = checkov_tool.policy_scan_checkov(fake_settings, path="")
    assert res["error"] == "validation_error"


def test_checkov_handles_invalid_json(monkeypatch, fake_settings, tmp_path):
    monkeypatch.setattr(
        checkov_tool, "run_command", lambda *a, **kw: _mock_result(stdout="not json")
    )
    res = checkov_tool.policy_scan_checkov(fake_settings, path=str(tmp_path))
    assert res["error"] == "invalid_json"
