"""Testes para os modelos pydantic de deploy-mcp-server."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.models.deploy import (
    CheckRun,
    DeployResult,
    FileChange,
    PRInfo,
    WorkflowRunInfo,
)


def test_file_change_requires_path_and_content():
    fc = FileChange(path="src/main.py", content="print('hi')")
    assert fc.path == "src/main.py"
    with pytest.raises(ValidationError):
        FileChange(path="only-path")  # type: ignore[call-arg]


def test_check_run_optional_conclusion():
    cr = CheckRun(name="ci", status="completed", url="http://x")
    assert cr.conclusion is None


def test_pr_info_defaults():
    pr = PRInfo(
        number=1,
        title="t",
        state="open",
        url="http://x",
        head="feature/x",
        base="develop",
        head_sha="abc1234",
    )
    assert pr.draft is False
    assert pr.checks == []
    assert pr.mergeable is None


def test_workflow_run_info_optional_fields():
    run = WorkflowRunInfo(id=1, status="completed", url="http://x")
    assert run.conclusion is None
    assert run.logs_url is None


def test_deploy_result_has_default_hint():
    dr = DeployResult(
        dispatched=True,
        workflow="cd-dev.yml",
        ref="develop",
        repo="my-repo",
        environment="dev",
        service="svc",
    )
    assert "list_workflow_runs" in dr.hint


def test_deploy_result_rejects_invalid_environment():
    with pytest.raises(ValidationError):
        DeployResult(
            dispatched=True,
            workflow="w",
            ref="r",
            repo="repo",
            environment="staging",  # type: ignore[arg-type]
            service="svc",
        )
