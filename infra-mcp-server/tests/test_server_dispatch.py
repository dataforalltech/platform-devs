"""Testes do dispatch do servidor MCP — sem precisar do SDK MCP rodando."""

from __future__ import annotations

import json

import pytest

from src.config.settings import Settings
from src.knowledge.allocator_store import AllocatorPolicy, AllocatorStore
from src.server.mcp_server import _TOOL_SCHEMAS, _dispatch
from src.tools import checkov_tool, infracost_tool, terraform_tool
from src.utils.subprocess_runner import CommandResult


def _mock_result(stdout: str = "", exit_code: int = 0) -> CommandResult:
    return CommandResult(
        cmd=["fake"], cwd="/", exit_code=exit_code, stdout=stdout,
        stderr="", duration_ms=1, truncated=False,
    )


@pytest.fixture
def allocator() -> AllocatorStore:
    return AllocatorStore(policy=AllocatorPolicy(max_cost_usd_per_hour=20.0))


def test_all_tools_registered():
    expected = {
        # Phase 1
        "terraform_validate",
        "terraform_fmt_check",
        "terraform_plan",
        "terraform_show_plan",
        "policy_scan_checkov",
        "cost_estimate_infracost",
        # Phase 2a
        "request_vm",
        "get_lease",
        "release_lease",
        "extend_lease",
        "list_my_leases",
        "list_pool",
        "query_capacity",
        # Phase 2f
        "get_lease_ssh_key",
        # Phase 2h
        "cancel_queued_request",
    }
    assert set(_TOOL_SCHEMAS.keys()) == expected


def test_each_schema_has_object_type():
    for name, meta in _TOOL_SCHEMAS.items():
        assert meta["schema"]["type"] == "object", f"{name} schema malformed"
        assert "description" in meta, f"{name} missing description"


def test_dispatch_unknown_tool(fake_settings):
    with pytest.raises(KeyError):
        _dispatch("does_not_exist", {}, fake_settings, allocator)


def test_dispatch_terraform_validate(monkeypatch, fake_settings, allocator):
    monkeypatch.setattr(
        terraform_tool, "run_command",
        lambda *a, **kw: _mock_result(stdout=json.dumps({"valid": True, "diagnostics": []})),
    )
    res = _dispatch("terraform_validate", {}, fake_settings, allocator)
    assert res["valid"] is True


def test_dispatch_policy_scan_requires_path(fake_settings):
    res = _dispatch("policy_scan_checkov", {}, fake_settings, allocator)
    assert res["error"] == "validation_error"


def test_dispatch_cost_estimate_requires_plan_path(fake_settings):
    res = _dispatch("cost_estimate_infracost", {}, fake_settings, allocator)
    assert res["error"] == "validation_error"


def test_dispatch_terraform_plan_uses_settings_root(monkeypatch, fake_settings, allocator):
    monkeypatch.setattr(
        terraform_tool, "run_command",
        lambda *a, **kw: _mock_result(stdout="No changes.", exit_code=0),
    )
    res = _dispatch("terraform_plan", {}, fake_settings, allocator)
    assert res["has_changes"] is False


def test_dispatch_show_plan_requires_plan_path(fake_settings):
    res = _dispatch("terraform_show_plan", {}, fake_settings, allocator)
    assert res["error"] == "validation_error"


def test_dispatch_checkov_passes_skip_checks(monkeypatch, fake_settings, tmp_path):
    captured = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        return _mock_result(stdout=json.dumps({"results": {"failed_checks": [], "passed_checks": []}}))

    monkeypatch.setattr(checkov_tool, "run_command", fake_run)
    _dispatch(
        "policy_scan_checkov",
        {"path": str(tmp_path), "skip_checks": ["CKV_AZ_42", "CKV_AZ_43"]},
        fake_settings,
        allocator,
    )
    assert "--skip-check" in captured["cmd"]
    skip_idx = captured["cmd"].index("--skip-check")
    assert captured["cmd"][skip_idx + 1] == "CKV_AZ_42,CKV_AZ_43"


def test_dispatch_infracost_custom_threshold(monkeypatch, fake_settings, tmp_path):
    plan = tmp_path / "x.tfplan"
    plan.write_text("bin")
    monkeypatch.setattr(
        infracost_tool, "run_command",
        lambda *a, **kw: _mock_result(
            stdout=json.dumps(
                {
                    "diffTotalMonthlyCost": "50",
                    "pastTotalMonthlyCost": "100",
                    "totalMonthlyCost": "150",
                    "currency": "USD",
                    "projects": [],
                }
            )
        ),
    )
    res = _dispatch(
        "cost_estimate_infracost",
        {"plan_path": str(plan), "delta_usd_threshold": 200, "delta_pct_threshold": 60},
        fake_settings,
        allocator,
    )
    # delta 50 USD < 200; pct 50% < 60% → no hard stop
    assert res["hard_stop"] is False


def test_dispatch_request_vm_allocator_path(fake_settings, allocator):
    res = _dispatch(
        "request_vm",
        {"spec": "cpu-small", "duration_min": 30, "owner": "agent-z"},
        fake_settings,
        allocator,
    )
    assert res["outcome"] == "LEASED"
    assert res["lease"]["spec"] == "cpu-small"


def test_dispatch_get_lease_after_request(fake_settings, allocator):
    leased = _dispatch(
        "request_vm",
        {"spec": "cpu-small", "duration_min": 30, "owner": "agent-z"},
        fake_settings,
        allocator,
    )
    lease_id = leased["lease"]["lease_id"]
    fetched = _dispatch("get_lease", {"lease_id": lease_id}, fake_settings, allocator)
    assert fetched["found"] is True
    assert fetched["lease"]["lease_id"] == lease_id


def test_dispatch_list_pool_starts_empty(fake_settings, allocator):
    pool = _dispatch("list_pool", {}, fake_settings, allocator)
    assert pool["vms"] == []


def test_dispatch_query_capacity_blocked_for_gpu(fake_settings, allocator):
    res = _dispatch(
        "query_capacity",
        {"spec": "gpu-a100"},
        fake_settings,
        allocator,
    )
    assert res["can_satisfy_now"] is False
    assert res["blocked_by"] == "approval_required"


def test_settings_uses_env_prefix(monkeypatch):
    monkeypatch.setenv("INFRA_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("INFRA_PLAN_TIMEOUT", "300")
    s = Settings()
    assert s.log_level == "DEBUG"
    assert s.plan_timeout == 300
