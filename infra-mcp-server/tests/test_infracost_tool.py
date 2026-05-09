"""Testes do cost_estimate_infracost."""

from __future__ import annotations

import json

from src.tools import infracost_tool
from src.utils.subprocess_runner import CommandResult


def _mock_result(stdout: str = "", stderr: str = "", exit_code: int = 0) -> CommandResult:
    return CommandResult(
        cmd=["fake"], cwd="/fake", exit_code=exit_code,
        stdout=stdout, stderr=stderr, duration_ms=10, truncated=False,
    )


def test_infracost_zero_diff(monkeypatch, fake_settings, tmp_path):
    plan = tmp_path / "x.tfplan"
    plan.write_text("binary")
    output = json.dumps(
        {
            "diffTotalMonthlyCost": "0.00",
            "pastTotalMonthlyCost": "100.00",
            "totalMonthlyCost": "100.00",
            "currency": "USD",
            "projects": [],
        }
    )
    monkeypatch.setattr(
        infracost_tool, "run_command", lambda *a, **kw: _mock_result(stdout=output)
    )
    res = infracost_tool.cost_estimate_infracost(fake_settings, plan_path=str(plan))
    assert res["monthly_diff"] == 0.0
    assert res["hard_stop"] is False


def test_infracost_small_increase_no_hard_stop(monkeypatch, fake_settings, tmp_path):
    plan = tmp_path / "x.tfplan"
    plan.write_text("binary")
    output = json.dumps(
        {
            "diffTotalMonthlyCost": "10.00",
            "pastTotalMonthlyCost": "100.00",
            "totalMonthlyCost": "110.00",
            "currency": "USD",
            "projects": [],
        }
    )
    monkeypatch.setattr(
        infracost_tool, "run_command", lambda *a, **kw: _mock_result(stdout=output)
    )
    res = infracost_tool.cost_estimate_infracost(fake_settings, plan_path=str(plan))
    assert res["monthly_diff"] == 10.0
    assert res["diff_percentage"] == 10.0  # 10/100
    assert res["hard_stop"] is False


def test_infracost_large_usd_diff_triggers_hard_stop(monkeypatch, fake_settings, tmp_path):
    plan = tmp_path / "x.tfplan"
    plan.write_text("binary")
    output = json.dumps(
        {
            "diffTotalMonthlyCost": "150.00",
            "pastTotalMonthlyCost": "1000.00",
            "totalMonthlyCost": "1150.00",
            "currency": "USD",
            "projects": [],
        }
    )
    monkeypatch.setattr(
        infracost_tool, "run_command", lambda *a, **kw: _mock_result(stdout=output)
    )
    res = infracost_tool.cost_estimate_infracost(fake_settings, plan_path=str(plan))
    assert res["hard_stop"] is True
    assert "150" in res["hard_stop_reason"]


def test_infracost_pct_threshold_triggers(monkeypatch, fake_settings, tmp_path):
    plan = tmp_path / "x.tfplan"
    plan.write_text("binary")
    output = json.dumps(
        {
            "diffTotalMonthlyCost": "30.00",
            "pastTotalMonthlyCost": "100.00",
            "totalMonthlyCost": "130.00",
            "currency": "USD",
            "projects": [],
        }
    )
    monkeypatch.setattr(
        infracost_tool, "run_command", lambda *a, **kw: _mock_result(stdout=output)
    )
    # USD threshold default 100 não ativa (delta 30); pct default 20% ativa (delta 30%)
    res = infracost_tool.cost_estimate_infracost(fake_settings, plan_path=str(plan))
    assert res["hard_stop"] is True
    assert "30.0%" in res["hard_stop_reason"]


def test_infracost_custom_thresholds(monkeypatch, fake_settings, tmp_path):
    plan = tmp_path / "x.tfplan"
    plan.write_text("binary")
    output = json.dumps(
        {
            "diffTotalMonthlyCost": "5.00",
            "pastTotalMonthlyCost": "100.00",
            "totalMonthlyCost": "105.00",
            "currency": "USD",
            "projects": [],
        }
    )
    monkeypatch.setattr(
        infracost_tool, "run_command", lambda *a, **kw: _mock_result(stdout=output)
    )
    # Threshold restritivo de 1 USD
    res = infracost_tool.cost_estimate_infracost(
        fake_settings,
        plan_path=str(plan),
        delta_usd_threshold=1.0,
    )
    assert res["hard_stop"] is True


def test_infracost_plan_not_found(fake_settings, tmp_path):
    res = infracost_tool.cost_estimate_infracost(
        fake_settings, plan_path=str(tmp_path / "nope.tfplan")
    )
    assert res["error"] == "plan_not_found"


def test_infracost_invalid_json(monkeypatch, fake_settings, tmp_path):
    plan = tmp_path / "x.tfplan"
    plan.write_text("binary")
    monkeypatch.setattr(
        infracost_tool, "run_command", lambda *a, **kw: _mock_result(stdout="not json")
    )
    res = infracost_tool.cost_estimate_infracost(fake_settings, plan_path=str(plan))
    assert res["error"] == "invalid_json"


def test_infracost_breakdown_extracted(monkeypatch, fake_settings, tmp_path):
    plan = tmp_path / "x.tfplan"
    plan.write_text("binary")
    output = json.dumps(
        {
            "diffTotalMonthlyCost": "10.00",
            "pastTotalMonthlyCost": "0.00",
            "totalMonthlyCost": "10.00",
            "currency": "USD",
            "projects": [
                {
                    "diff": {
                        "resources": [
                            {"name": "azurerm_storage_account.x", "monthlyCost": "5.50"},
                            {"name": "azurerm_app_service.y", "monthlyCost": "4.50"},
                        ]
                    }
                }
            ],
        }
    )
    monkeypatch.setattr(
        infracost_tool, "run_command", lambda *a, **kw: _mock_result(stdout=output)
    )
    res = infracost_tool.cost_estimate_infracost(fake_settings, plan_path=str(plan))
    assert len(res["breakdown"]) == 2
    names = {b["name"] for b in res["breakdown"]}
    assert "azurerm_storage_account.x" in names
