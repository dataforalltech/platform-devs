"""Regressões bloqueantes para a decisão de operar sem GitHub Actions."""

from __future__ import annotations

from pathlib import Path

from src.server.mcp_server import _RETIRED_GITHUB_ACTION_TOOLS, _TOOL_SCHEMAS


ROOT = Path(__file__).resolve().parents[1]


def test_retired_tools_are_not_exposed():
    assert _RETIRED_GITHUB_ACTION_TOOLS.isdisjoint(_TOOL_SCHEMAS)


def test_no_workflow_generators_remain():
    forbidden = [
        ROOT / "src/tools/pipeline_tool.py",
        ROOT / "src/tools/workflow_tool.py",
        ROOT / "src/knowledge/pipeline_templates",
    ]
    assert not [path for path in forbidden if path.exists()]


def test_low_level_actions_client_has_no_actions_api(client):
    retired_methods = {
        "trigger_workflow",
        "list_workflow_runs",
        "get_workflow_run",
        "cancel_workflow_run",
        "set_repo_secret",
        "set_repo_variable",
    }
    assert not [name for name in retired_methods if hasattr(client, name)]
