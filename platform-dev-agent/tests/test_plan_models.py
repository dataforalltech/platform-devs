"""Tests for the PlanItem 'tool' namespaced validator."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.dev_agent.models.plan import Capability, ItemStatus, PlanItem, RiskLevel


def _item(tool: str) -> PlanItem:
    return PlanItem(
        plan_id="p1",
        sequence_num=1,
        runbook_id="rb",
        task_id="t",
        tool=tool,
        capability=Capability.READ,
        label="label",
        responsible="qa-engineer",
    )


def test_tool_accepts_namespaced() -> None:
    item = _item("a.b")
    assert item.tool == "a.b"
    assert item.required is True  # default
    assert item.status is ItemStatus.PENDING


def test_tool_accepts_real_gateway_name() -> None:
    assert _item("qa-mcp.run_tests").tool == "qa-mcp.run_tests"


def test_tool_rejects_url() -> None:
    with pytest.raises(ValidationError):
        _item("http://x")


def test_tool_rejects_missing_dot() -> None:
    with pytest.raises(ValidationError):
        _item("sem_ponto")


def test_tool_rejects_space() -> None:
    with pytest.raises(ValidationError):
        _item("a. b")


def test_needs_reconfirm_status_exists() -> None:
    assert ItemStatus.NEEDS_RECONFIRM.value == "needs_reconfirm"


def test_risk_default_is_low() -> None:
    assert _item("a.b").risk is RiskLevel.LOW
