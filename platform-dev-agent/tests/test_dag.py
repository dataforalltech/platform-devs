"""Tests for topological ordering: happy path, cycle, orphaned depends_on."""

from __future__ import annotations

import pytest

from app.dev_agent.runbook.catalog import RunbookSpec, RunbookTaskSpec
from app.dev_agent.runbook.dag import RunbookDAGError, topological_order


def _task(tool: str, depends_on: list[str] | None = None) -> RunbookTaskSpec:
    return RunbookTaskSpec(
        title="t",
        description="d",
        required=True,
        responsible="qa-engineer",
        tool=tool,
        input_schema={},
        depends_on=depends_on or [],
    )


def _rb(tasks: dict[str, RunbookTaskSpec]) -> RunbookSpec:
    return RunbookSpec(
        id="rb",
        version="1.0.0",
        name="n",
        description="d",
        responsible_profile="qa-engineer",
        tasks=tasks,
    )


def test_topological_order_linear_ok() -> None:
    rb = _rb(
        {
            "a": _task("services-mcp.check_health"),
            "b": _task("qa-mcp.run_tests", depends_on=["a"]),
            "c": _task("qa-mcp.generate_report", depends_on=["b"]),
        }
    )
    assert topological_order(rb) == ["a", "b", "c"]


def test_topological_order_respects_dependencies() -> None:
    # diamond: a -> {b, c} -> d
    rb = _rb(
        {
            "a": _task("services-mcp.check_health"),
            "b": _task("qa-mcp.run_tests", depends_on=["a"]),
            "c": _task("qa-mcp.check_coverage", depends_on=["a"]),
            "d": _task("qa-mcp.generate_report", depends_on=["b", "c"]),
        }
    )
    order = topological_order(rb)
    assert order.index("a") < order.index("b")
    assert order.index("a") < order.index("c")
    assert order.index("b") < order.index("d")
    assert order.index("c") < order.index("d")


def test_topological_order_cycle_raises() -> None:
    rb = _rb(
        {
            "a": _task("qa-mcp.run_tests", depends_on=["b"]),
            "b": _task("qa-mcp.check_coverage", depends_on=["a"]),
        }
    )
    with pytest.raises(RunbookDAGError, match="cycle"):
        topological_order(rb)


def test_topological_order_orphan_dependency_raises() -> None:
    rb = _rb(
        {
            "a": _task("qa-mcp.run_tests", depends_on=["does_not_exist"]),
        }
    )
    with pytest.raises(RunbookDAGError, match="does not exist"):
        topological_order(rb)
