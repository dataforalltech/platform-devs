"""Testes para tools de deploy: deploy, get_deploy_status."""

from __future__ import annotations

from unittest.mock import MagicMock

from src.tools.deploy_tool import deploy, get_deploy_status

from .conftest import make_mock_repo, make_mock_run


class TestDeploy:
    def test_deploy_to_dev_uses_cd_dev_workflow(self, client, mock_github):
        mock_repo = make_mock_repo()
        mock_github.get_repo.return_value = mock_repo
        mock_wf = MagicMock()
        mock_wf.create_dispatch.return_value = True
        mock_repo.get_workflow.return_value = mock_wf

        result = deploy(client, service="platform-analytics", environment="dev")

        mock_repo.get_workflow.assert_called_with("cd-dev.yml")
        mock_wf.create_dispatch.assert_called_with(ref="develop", inputs={})
        assert result["environment"] == "dev"
        assert result["service"] == "platform-analytics"
        assert result["workflow"] == "cd-dev.yml"

    def test_deploy_to_hml_requires_ref(self, client):
        result = deploy(client, service="platform-analytics", environment="hml")
        assert result["error"] == "ValidationError"
        assert "release/" in result["details"]

    def test_deploy_to_hml_with_ref(self, client, mock_github):
        mock_repo = make_mock_repo()
        mock_github.get_repo.return_value = mock_repo
        mock_wf = MagicMock()
        mock_wf.create_dispatch.return_value = True
        mock_repo.get_workflow.return_value = mock_wf

        result = deploy(
            client,
            service="platform-analytics",
            environment="hml",
            ref="release/1.3.0",
        )

        mock_wf.create_dispatch.assert_called_with(ref="release/1.3.0", inputs={})
        assert result["workflow"] == "cd-hml.yml"

    def test_deploy_to_prod_requires_ref(self, client):
        result = deploy(client, service="platform-analytics", environment="prod")
        assert result["error"] == "ValidationError"
        assert "v" in result["details"]  # hint menciona v<semver>

    def test_deploy_to_prod_with_tag(self, client, mock_github):
        mock_repo = make_mock_repo()
        mock_github.get_repo.return_value = mock_repo
        mock_wf = MagicMock()
        mock_wf.create_dispatch.return_value = True
        mock_repo.get_workflow.return_value = mock_wf

        result = deploy(
            client,
            service="platform-analytics",
            environment="prod",
            ref="v1.3.0",
        )

        mock_repo.get_workflow.assert_called_with("cd-prod.yml")
        assert result["workflow"] == "cd-prod.yml"

    def test_invalid_environment_returns_validation_error(self, client):
        result = deploy(client, service="svc", environment="staging")
        assert result["error"] == "ValidationError"
        assert "dev, hml ou prod" in result["details"]

    def test_uses_repo_param_when_different_from_service(self, client, mock_github):
        mock_repo = make_mock_repo(name="platform-analytics-new")
        mock_github.get_repo.return_value = mock_repo
        mock_wf = MagicMock()
        mock_wf.create_dispatch.return_value = True
        mock_repo.get_workflow.return_value = mock_wf

        deploy(
            client,
            service="analytics",
            environment="dev",
            repo="platform-analytics-new",
        )

        # Verifica que usou o repo explícito
        mock_github.get_repo.assert_called_with("test-org/platform-analytics-new")

    def test_passes_inputs_to_workflow(self, client, mock_github):
        mock_repo = make_mock_repo()
        mock_github.get_repo.return_value = mock_repo
        mock_wf = MagicMock()
        mock_wf.create_dispatch.return_value = True
        mock_repo.get_workflow.return_value = mock_wf

        deploy(
            client,
            service="svc",
            environment="dev",
            inputs={"force_rebuild": "true"},
        )

        mock_wf.create_dispatch.assert_called_with(
            ref="develop",
            inputs={"force_rebuild": "true"},
        )


class TestGetDeployStatus:
    def test_returns_recent_runs_for_dev(self, client, mock_github):
        mock_repo = make_mock_repo()
        mock_github.get_repo.return_value = mock_repo
        mock_wf = MagicMock()
        runs = [make_mock_run(i, name="CD DEV") for i in range(1, 4)]
        mock_wf.get_runs.return_value = iter(runs)
        mock_repo.get_workflow.return_value = mock_wf

        result = get_deploy_status(client, service="platform-analytics", environment="dev")

        assert result["service"] == "platform-analytics"
        assert result["environment"] == "dev"
        assert result["workflow"] == "cd-dev.yml"
        assert result["count"] == 3

    def test_returns_recent_runs_for_prod(self, client, mock_github):
        mock_repo = make_mock_repo()
        mock_github.get_repo.return_value = mock_repo
        mock_wf = MagicMock()
        runs = [make_mock_run(1, name="CD PROD")]
        mock_wf.get_runs.return_value = iter(runs)
        mock_repo.get_workflow.return_value = mock_wf

        result = get_deploy_status(client, service="svc", environment="prod")

        assert result["workflow"] == "cd-prod.yml"

    def test_invalid_environment_returns_error(self, client):
        result = get_deploy_status(client, service="svc", environment="staging")
        assert result["error"] == "ValidationError"

    def test_missing_service_returns_error(self, client):
        result = get_deploy_status(client, service="", environment="dev")
        assert result["error"] == "ValidationError"

    def test_respects_limit(self, client, mock_github):
        mock_repo = make_mock_repo()
        mock_github.get_repo.return_value = mock_repo
        mock_wf = MagicMock()
        runs = [make_mock_run(i) for i in range(1, 15)]
        mock_wf.get_runs.return_value = iter(runs)
        mock_repo.get_workflow.return_value = mock_wf

        result = get_deploy_status(client, service="svc", environment="dev", limit=3)

        assert result["count"] == 3
