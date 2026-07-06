"""Tests for PlanBuilder: topological order, capability/risk, input validation."""

from __future__ import annotations

import pytest

from app.dev_agent.capability import CapabilityResolver
from app.dev_agent.catalog import DirCatalogSource, RegistryCapabilityResolver
from app.dev_agent.models.plan import Capability, RiskLevel
from app.dev_agent.plan.builder import PlanBuilder, PlanValidationError
from app.dev_agent.runbook.catalog import RunbookSpec, RunbookTaskSpec, get_runbook


def _builder() -> PlanBuilder:
    return PlanBuilder(CapabilityResolver())


def test_build_from_real_runbook_topological_order() -> None:
    plan = _builder().build_from_runbook(
        runbook_id="health_to_report",
        session_id="s1",
        inputs_by_task={
            "check_health": {"service": "api"},
            "run_tests": {"suite": "unit"},
        },
    )
    assert [i.task_id for i in plan.items] == ["check_health", "run_tests", "generate_report"]
    assert [i.sequence_num for i in plan.items] == [1, 2, 3]
    assert plan.runbook_version == "1.0.0"
    assert plan.runbook_id == "health_to_report"


def test_build_resolves_read_capability_and_low_risk() -> None:
    plan = _builder().build_from_runbook(
        runbook_id="health_to_report",
        session_id="s1",
        inputs_by_task={
            "check_health": {"service": "api"},
            "run_tests": {"suite": "unit"},
        },
    )
    for item in plan.items:
        assert item.capability is Capability.READ
        assert item.risk is RiskLevel.LOW  # read => low
    # 'required' propagated from the runbook spec
    by_task = {i.task_id: i for i in plan.items}
    assert by_task["check_health"].required is True
    assert by_task["generate_report"].required is False


def test_build_write_deploy_owner_is_high_risk() -> None:
    """A write on a destructive owner (deploy/infra/pipeline) => HIGH risk."""
    rb = RunbookSpec(
        id="deploy_rb",
        version="0.1.0",
        name="deploy",
        description="d",
        responsible_profile="devops",
        tasks={
            "dep": RunbookTaskSpec(
                title="deploy it",
                description="d",
                required=True,
                responsible="devops",
                tool="deploy-mcp.create_deployment",
                input_schema={"type": "object", "properties": {}, "required": []},
            ),
        },
    )
    # Inject via the resolver directly (builder reads from the catalog),
    # so exercise the resolver's classification here.
    caps = CapabilityResolver()
    cap = caps.resolve(rb.tasks["dep"].tool)
    assert cap is Capability.WRITE  # create_ prefix
    assert caps.classify_risk(rb.tasks["dep"].tool, cap) is RiskLevel.HIGH


def test_build_write_non_destructive_owner_is_medium_risk() -> None:
    caps = CapabilityResolver()
    cap = caps.resolve("docs-mcp.generate_doc")
    assert cap is Capability.WRITE  # generate_ prefix
    assert caps.classify_risk("docs-mcp.generate_doc", cap) is RiskLevel.MEDIUM


def test_build_fails_early_on_missing_required_inputs() -> None:
    with pytest.raises(PlanValidationError, match="missing required input"):
        _builder().build_from_runbook(
            runbook_id="health_to_report",
            session_id="s1",
            inputs_by_task={
                # check_health requires 'service' — omit it
                "check_health": {"wrong_key": "x"},
                "run_tests": {"suite": "unit"},
            },
        )


def test_build_fails_early_on_no_inputs_for_required_task() -> None:
    with pytest.raises(PlanValidationError, match="required but received no inputs"):
        _builder().build_from_runbook(
            runbook_id="health_to_report",
            session_id="s1",
            inputs_by_task={
                "run_tests": {"suite": "unit"},
                # check_health omitted entirely -> {} -> required with required props
            },
        )


def test_build_wrong_input_type_rejected() -> None:
    with pytest.raises(PlanValidationError, match="must be string"):
        _builder().build_from_runbook(
            runbook_id="health_to_report",
            session_id="s1",
            inputs_by_task={
                "check_health": {"service": 123},
                "run_tests": {"suite": "unit"},
            },
        )


def test_selected_tasks_filters_items() -> None:
    plan = _builder().build_from_runbook(
        runbook_id="health_to_report",
        session_id="s1",
        inputs_by_task={"check_health": {"service": "api"}},
        selected_tasks={"check_health"},
    )
    assert [i.task_id for i in plan.items] == ["check_health"]


def test_get_runbook_unknown_raises() -> None:
    with pytest.raises(ValueError, match="does not exist"):
        get_runbook("nope")


# --- Fase 6: Operation-first path (catalog resolves Operation -> record + tool) ---
def test_dir_source_resolves_operation_to_record_and_tool() -> None:
    """DirCatalogSource resolves delivery.deploy to a write/high record and a
    concrete <provider>.<op> tool (hermetic — reads the real Fase-1 catalog)."""
    src = DirCatalogSource()
    rec = src.record_for_operation("delivery.deploy")
    assert rec is not None
    assert rec.capability == "write" and rec.risk_level == "high"
    tool = src.tool_for_operation("delivery.deploy")
    assert tool and "." in tool           # concrete <provider>.<op>
    assert src.record(tool) is rec         # deterministic pick points at that record


def test_build_operation_first_hotfix_deploy_is_write_high() -> None:
    """PlanBuilder over the Operation-first 'hotfix' runbook stamps the deploy
    item as write/high with a non-empty resolved gateway tool (no gateway)."""
    builder = PlanBuilder(RegistryCapabilityResolver(DirCatalogSource()))
    plan = builder.build_from_runbook(runbook_id="hotfix", session_id="s")
    by_task = {i.task_id: i for i in plan.items}
    deploy = by_task["deploy"]
    assert deploy.capability is Capability.WRITE
    assert deploy.risk is RiskLevel.HIGH
    assert deploy.tool and deploy.tool != "delivery.deploy"   # concrete tool, not the op uid


def test_operation_first_and_legacy_are_mutually_exclusive() -> None:
    """RunbookTaskSpec enforces exactly one of operation_id / tool."""
    common = dict(title="t", description="d", required=True, responsible="devops",
                  input_schema={"type": "object", "properties": {}, "required": []})
    with pytest.raises(ValueError, match="exactly one"):
        RunbookTaskSpec(**common)                                   # neither set
    with pytest.raises(ValueError, match="exactly one"):
        RunbookTaskSpec(**common, tool="a.b", operation_id="x.y")   # both set
