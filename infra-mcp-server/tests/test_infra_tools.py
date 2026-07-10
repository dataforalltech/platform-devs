"""Testes das tools reais via _dispatch — saída DERIVADA dos inputs.

Exercita o roteamento do dispatcher para as 15 tools de negócio (terraform/checkov/
infracost via subprocess mockado + allocator SQLite :memory:), garantindo que a
migração da camada de transporte preservou a lógica de negócio. Sem I/O externo:
``run_command`` é sempre mockado e o allocator usa SQLite em memória.
"""

from __future__ import annotations

import json

import pytest

from src.config.settings import Settings
from src.db.allocator_store import AllocatorPolicy, AllocatorStore
from src.server.mcp_server import _TOOL_SCHEMAS, _dispatch
from src.tools import checkov_tool, infracost_tool, terraform_tool
from src.utils.subprocess_runner import CommandResult


def _mock_result(stdout: str = "", exit_code: int = 0) -> CommandResult:
    return CommandResult(
        cmd=["fake"],
        cwd="/",
        exit_code=exit_code,
        stdout=stdout,
        stderr="",
        duration_ms=1,
        truncated=False,
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


def test_each_schema_has_object_type_and_policy_fields():
    for name, meta in _TOOL_SCHEMAS.items():
        assert meta["schema"]["type"] == "object", f"{name} schema malformed"
        assert "description" in meta, f"{name} missing description"
        for field in ("capability", "required_scope", "resource_type", "data_domain"):
            assert meta[field], f"{name} sem {field}"


def test_dispatch_unknown_tool(fake_settings, allocator):
    with pytest.raises(KeyError):
        _dispatch("does_not_exist", {}, fake_settings, allocator)


def test_dispatch_strips_tenant_id(monkeypatch, fake_settings, allocator):
    """tenant_id injetado pelo PEP é removido antes de chamar a tool (INV-3)."""
    monkeypatch.setattr(
        terraform_tool,
        "run_command",
        lambda *a, **kw: _mock_result(stdout=json.dumps({"valid": True, "diagnostics": []})),
    )
    # tenant_id extra NÃO deve virar erro de argumento inesperado
    res = _dispatch("terraform_validate", {"tenant_id": "T-9"}, fake_settings, allocator)
    assert res["valid"] is True


def test_dispatch_terraform_validate(monkeypatch, fake_settings, allocator):
    monkeypatch.setattr(
        terraform_tool,
        "run_command",
        lambda *a, **kw: _mock_result(stdout=json.dumps({"valid": True, "diagnostics": []})),
    )
    res = _dispatch("terraform_validate", {}, fake_settings, allocator)
    assert res["valid"] is True


def test_dispatch_terraform_fmt_check(monkeypatch, fake_settings, allocator):
    monkeypatch.setattr(
        terraform_tool,
        "run_command",
        lambda *a, **kw: _mock_result(stdout="", exit_code=0),
    )
    res = _dispatch("terraform_fmt_check", {"recursive": False}, fake_settings, allocator)
    assert res["is_formatted"] is True


def test_dispatch_policy_scan_requires_path(fake_settings, allocator):
    res = _dispatch("policy_scan_checkov", {}, fake_settings, allocator)
    assert res["error"] == "validation_error"


def test_dispatch_cost_estimate_requires_plan_path(fake_settings, allocator):
    res = _dispatch("cost_estimate_infracost", {}, fake_settings, allocator)
    assert res["error"] == "validation_error"


def test_dispatch_terraform_plan_uses_settings_root(monkeypatch, fake_settings, allocator):
    monkeypatch.setattr(
        terraform_tool,
        "run_command",
        lambda *a, **kw: _mock_result(stdout="No changes.", exit_code=0),
    )
    res = _dispatch("terraform_plan", {}, fake_settings, allocator)
    assert res["has_changes"] is False


def test_dispatch_show_plan_requires_plan_path(fake_settings, allocator):
    res = _dispatch("terraform_show_plan", {}, fake_settings, allocator)
    assert res["error"] == "validation_error"


def test_dispatch_checkov_passes_skip_checks(monkeypatch, fake_settings, allocator, tmp_path):
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


def test_dispatch_infracost_custom_threshold(monkeypatch, fake_settings, allocator, tmp_path):
    plan = tmp_path / "x.tfplan"
    plan.write_text("bin")
    monkeypatch.setattr(
        infracost_tool,
        "run_command",
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


def test_dispatch_release_and_extend_lease(fake_settings, allocator):
    leased = _dispatch(
        "request_vm",
        {"spec": "cpu-small", "duration_min": 30, "owner": "agent-z"},
        fake_settings,
        allocator,
    )
    lease_id = leased["lease"]["lease_id"]
    extended = _dispatch(
        "extend_lease",
        {"lease_id": lease_id, "additional_min": 15},
        fake_settings,
        allocator,
    )
    assert "lease" in extended and extended["lease"]["lease_id"] == lease_id
    released = _dispatch("release_lease", {"lease_id": lease_id, "by": "agent-z"}, fake_settings, allocator)
    assert "lease" in released and released["lease"]["lease_id"] == lease_id


def test_dispatch_list_my_leases(fake_settings, allocator):
    _dispatch(
        "request_vm",
        {"spec": "cpu-small", "duration_min": 30, "owner": "agent-l"},
        fake_settings,
        allocator,
    )
    res = _dispatch("list_my_leases", {"owner": "agent-l"}, fake_settings, allocator)
    assert res["owner"] == "agent-l"
    assert len(res["leases"]) >= 1


def test_dispatch_list_pool_starts_empty(fake_settings, allocator):
    pool = _dispatch("list_pool", {}, fake_settings, allocator)
    assert pool["vms"] == []


def test_dispatch_query_capacity_blocked_for_gpu(fake_settings, allocator):
    res = _dispatch("query_capacity", {"spec": "gpu-a100"}, fake_settings, allocator)
    assert res["can_satisfy_now"] is False
    assert res["blocked_by"] == "approval_required"


def test_dispatch_get_lease_ssh_key_requires_active(fake_settings, allocator):
    res = _dispatch(
        "get_lease_ssh_key",
        {"lease_id": "nonexistent", "owner": "agent-z"},
        fake_settings,
        allocator,
    )
    assert "error" in res


def test_dispatch_cancel_queued_request_unknown(fake_settings, allocator):
    res = _dispatch(
        "cancel_queued_request",
        {"request_id": "does-not-exist", "by": "agent-z"},
        fake_settings,
        allocator,
    )
    assert "error" in res


def test_settings_uses_env_prefix_and_canonical_aliases(monkeypatch):
    # log_level agora usa a env-var canônica MCP_SERVICE_LOG_LEVEL (validation_alias)
    monkeypatch.setenv("MCP_SERVICE_LOG_LEVEL", "DEBUG")
    # demais campos permanecem com o prefixo INFRA_
    monkeypatch.setenv("INFRA_PLAN_TIMEOUT", "300")
    s = Settings()
    assert s.log_level == "DEBUG"
    assert s.plan_timeout == 300
    # audiência default derivada do namespace
    assert s.mcp_twin_audience == "mcp:infra-mcp"
