"""Testes para tools de Workflow: trigger_workflow, list_workflow_runs, get_workflow_run, cancel_workflow_run."""

from __future__ import annotations

from unittest.mock import MagicMock

from src.tools.workflow_tool import (
    cancel_workflow_run,
    get_workflow_run,
    list_workflow_runs,
    trigger_workflow,
)

from .conftest import make_mock_repo, make_mock_run


class TestTriggerWorkflow:
    def test_dispatches_workflow_successfully(self, client, mock_github):
        mock_repo = make_mock_repo()
        mock_github.get_repo.return_value = mock_repo
        mock_wf = MagicMock()
        mock_wf.create_dispatch.return_value = True
        mock_repo.get_workflow.return_value = mock_wf

        result = trigger_workflow(
            client,
            repo="my-repo",
            workflow_id="cd-dev.yml",
            ref="develop",
        )

        mock_wf.create_dispatch.assert_called_once_with(ref="develop", inputs={})
        assert result["dispatched"] is True
        assert result["workflow"] == "cd-dev.yml"
        assert result["ref"] == "develop"

    def test_passes_inputs_to_dispatch(self, client, mock_github):
        mock_repo = make_mock_repo()
        mock_github.get_repo.return_value = mock_repo
        mock_wf = MagicMock()
        mock_wf.create_dispatch.return_value = True
        mock_repo.get_workflow.return_value = mock_wf

        trigger_workflow(
            client,
            repo="my-repo",
            workflow_id="deploy.yml",
            ref="main",
            inputs={"environment": "production", "tag": "v1.0.0"},
        )

        mock_wf.create_dispatch.assert_called_once_with(
            ref="main",
            inputs={"environment": "production", "tag": "v1.0.0"},
        )

    def test_workflow_not_found_returns_error(self, client, mock_github):
        from github.GithubException import UnknownObjectException

        mock_repo = make_mock_repo()
        mock_github.get_repo.return_value = mock_repo
        mock_repo.get_workflow.side_effect = UnknownObjectException(404, "Not Found")

        result = trigger_workflow(
            client, repo="my-repo", workflow_id="nonexistent.yml", ref="develop"
        )

        assert "error" in result
        assert "não encontrado" in result["details"]

    def test_missing_required_params_returns_validation_error(self, client):
        result = trigger_workflow(client, repo="", workflow_id="ci.yml", ref="develop")
        assert result["error"] == "ValidationError"


class TestListWorkflowRuns:
    def test_returns_runs_list(self, client, mock_github):
        mock_repo = make_mock_repo()
        mock_github.get_repo.return_value = mock_repo
        mock_wf = MagicMock()
        runs = [make_mock_run(i, status="completed", conclusion="success") for i in range(1, 4)]
        mock_wf.get_runs.return_value = iter(runs)
        mock_repo.get_workflow.return_value = mock_wf

        result = list_workflow_runs(client, repo="my-repo", workflow_id="cd-dev.yml")

        assert result["count"] == 3
        assert result["runs"][0]["status"] == "completed"

    def test_respects_limit(self, client, mock_github):
        mock_repo = make_mock_repo()
        mock_github.get_repo.return_value = mock_repo
        mock_wf = MagicMock()
        runs = [make_mock_run(i) for i in range(1, 20)]
        mock_wf.get_runs.return_value = iter(runs)
        mock_repo.get_workflow.return_value = mock_wf

        result = list_workflow_runs(client, repo="my-repo", workflow_id="ci.yml", limit=5)

        assert result["count"] == 5

    def test_unknown_workflow_returns_empty(self, client, mock_github):
        from github.GithubException import UnknownObjectException

        mock_repo = make_mock_repo()
        mock_github.get_repo.return_value = mock_repo
        mock_repo.get_workflow.side_effect = UnknownObjectException(404, "Not Found")

        result = list_workflow_runs(client, repo="my-repo", workflow_id="ghost.yml")

        assert result["runs"] == []
        assert result["count"] == 0

    def test_missing_repo_returns_validation_error(self, client):
        result = list_workflow_runs(client, repo="")
        assert result["error"] == "ValidationError"

    def test_without_workflow_id_lists_all(self, client, mock_github):
        mock_repo = make_mock_repo()
        mock_github.get_repo.return_value = mock_repo
        runs = [make_mock_run(1), make_mock_run(2)]
        mock_repo.get_workflow_runs.return_value = iter(runs)

        result = list_workflow_runs(client, repo="my-repo")

        mock_repo.get_workflow_runs.assert_called_once()
        assert result["count"] == 2


class TestGetWorkflowRun:
    def test_returns_run_with_logs_url(self, client, mock_github):
        mock_repo = make_mock_repo()
        mock_github.get_repo.return_value = mock_repo
        run = make_mock_run(99, status="in_progress", conclusion=None)
        mock_repo.get_workflow_run.return_value = run

        result = get_workflow_run(client, repo="my-repo", run_id=99)

        assert result["id"] == 99
        assert result["status"] == "in_progress"
        assert "logs_url" in result

    def test_not_found_returns_error(self, client, mock_github):
        from github.GithubException import UnknownObjectException

        mock_repo = make_mock_repo()
        mock_github.get_repo.return_value = mock_repo
        mock_repo.get_workflow_run.side_effect = UnknownObjectException(404, "Not Found")

        result = get_workflow_run(client, repo="my-repo", run_id=9999)

        assert "error" in result
        assert "não encontrado" in result["details"]

    def test_missing_params_returns_validation_error(self, client):
        result = get_workflow_run(client, repo="", run_id=0)
        assert result["error"] == "ValidationError"


class TestCancelWorkflowRun:
    def test_cancels_run_successfully(self, client, mock_github):
        mock_repo = make_mock_repo()
        mock_github.get_repo.return_value = mock_repo
        run = make_mock_run(55, status="in_progress")
        run.cancel.return_value = True
        mock_repo.get_workflow_run.return_value = run

        result = cancel_workflow_run(client, repo="my-repo", run_id=55)

        run.cancel.assert_called_once()
        assert result["cancelled"] is True
        assert result["run_id"] == 55

    def test_run_not_found_returns_error(self, client, mock_github):
        from github.GithubException import UnknownObjectException

        mock_repo = make_mock_repo()
        mock_github.get_repo.return_value = mock_repo
        mock_repo.get_workflow_run.side_effect = UnknownObjectException(404, "Not Found")

        result = cancel_workflow_run(client, repo="my-repo", run_id=9999)

        assert "error" in result
