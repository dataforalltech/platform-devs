"""Testes para tools de ACR: setup_repo, acr_build, list_acr_images.

Todo I/O externo (docker CLI, git, GitHub API, ACR REST) é mockado — nada roda de verdade.
"""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock

import pytest

from src.config.settings import DeploySettings
from src.knowledge.github_client import GitHubClientError
from src.tools.acr_tool import acr_build, list_acr_images, setup_repo


@pytest.fixture
def acr_settings() -> DeploySettings:
    """Settings com credenciais ACR configuradas."""
    return DeploySettings(
        github_token="test_token",
        github_org="test-org",
        acr_registry="test.azurecr.io",
        acr_namespace="test/3.0",
        acr_username="acr-user",
        acr_password="acr-pass",
    )


@pytest.fixture
def no_acr_settings() -> DeploySettings:
    """Settings SEM credenciais ACR (username/password None) — para paths de ConfigError."""
    return DeploySettings(
        github_token="test_token",
        github_org="test-org",
        acr_registry="test.azurecr.io",
        acr_namespace="test/3.0",
        acr_username=None,
        acr_password=None,
    )


# ─────────────────────────────────────────────────────────────────────────── #
# setup_repo                                                                    #
# ─────────────────────────────────────────────────────────────────────────── #
class TestSetupRepo:
    def test_missing_acr_credentials_returns_config_error(self, client, no_acr_settings):
        result = setup_repo(client, no_acr_settings, repo="my-repo", image_name="my-img")
        assert result["error"] == "ConfigError"
        assert "DEPLOY_ACR_USERNAME" in result["details"]

    def test_configures_secrets_and_variable(self, client, acr_settings):
        client.set_repo_secret = MagicMock(return_value={"status": "ok"})
        client.set_repo_variable = MagicMock(return_value={"status": "ok"})

        result = setup_repo(client, acr_settings, repo="my-repo", image_name="platform-x")

        assert result["success"] is True
        assert result["errors"] == []
        # ACR_USERNAME + ACR_PASSWORD como secrets
        secret_calls = {c.args[1] for c in client.set_repo_secret.call_args_list}
        assert secret_calls == {"ACR_USERNAME", "ACR_PASSWORD"}
        client.set_repo_variable.assert_called_once_with("my-repo", "IMAGE_NAME", "platform-x")
        assert result["registry"] == "test.azurecr.io/test/3.0/platform-x"
        assert "trigger_workflow" in result["next_step"]

    def test_includes_optional_secrets(self, client, acr_settings):
        client.set_repo_secret = MagicMock(return_value={"status": "ok"})
        client.set_repo_variable = MagicMock(return_value={"status": "ok"})

        setup_repo(
            client,
            acr_settings,
            repo="my-repo",
            image_name="img",
            portainer_webhook="https://portainer/webhook",
            github_token="ghp_extra",
        )

        secret_names = {c.args[1] for c in client.set_repo_secret.call_args_list}
        assert "PORTAINER_WEBHOOK_URL" in secret_names
        assert "TOKEN_GITHUB" in secret_names

    def test_secret_error_collected_and_success_false(self, client, acr_settings):
        def fail_on_password(repo, name, value):
            if name == "ACR_PASSWORD":
                raise GitHubClientError("boom")
            return {"status": "ok"}

        client.set_repo_secret = MagicMock(side_effect=fail_on_password)
        client.set_repo_variable = MagicMock(return_value={"status": "ok"})

        result = setup_repo(client, acr_settings, repo="my-repo", image_name="img")

        assert result["success"] is False
        assert any(e["name"] == "ACR_PASSWORD" for e in result["errors"])
        assert "Corrija os erros" in result["next_step"]

    def test_variable_error_collected(self, client, acr_settings):
        client.set_repo_secret = MagicMock(return_value={"status": "ok"})
        client.set_repo_variable = MagicMock(side_effect=GitHubClientError("var fail"))

        result = setup_repo(client, acr_settings, repo="my-repo", image_name="img")

        assert result["success"] is False
        assert any(e["name"] == "IMAGE_NAME" for e in result["errors"])


# ─────────────────────────────────────────────────────────────────────────── #
# acr_build                                                                     #
# ─────────────────────────────────────────────────────────────────────────── #
def _proc(returncode=0, stdout="", stderr=""):
    m = MagicMock()
    m.returncode = returncode
    m.stdout = stdout
    m.stderr = stderr
    return m


class TestAcrBuild:
    def test_missing_credentials_returns_config_error(self, no_acr_settings):
        result = acr_build(no_acr_settings, repo_path="/tmp/repo", image_name="img")
        assert result["error"] == "ConfigError"

    def test_full_build_and_push_success(self, acr_settings, monkeypatch):
        calls: list[list[str]] = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            return _proc(returncode=0, stdout="ok")

        monkeypatch.setattr(subprocess, "run", fake_run)

        result = acr_build(
            acr_settings,
            repo_path="/tmp/repo",
            image_name="platform-x",
            tag="v9.9",
        )

        assert result["success"] is True
        assert result["tag"] == "v9.9"
        assert result["pushed"] is True
        assert result["image"] == "test.azurecr.io/test/3.0/platform-x:v9.9"
        # login + build + 2 pushes (vtag + latest)
        cmd_verbs = [c[1] for c in calls]
        assert cmd_verbs == ["login", "build", "push", "push"]

    def test_default_tag_uses_git_sha(self, acr_settings, monkeypatch):
        def fake_run(cmd, **kwargs):
            if cmd[:2] == ["git", "rev-parse"]:
                return _proc(returncode=0, stdout="abc1234\n")
            return _proc(returncode=0)

        monkeypatch.setattr(subprocess, "run", fake_run)

        result = acr_build(acr_settings, repo_path="/tmp/repo", image_name="img")

        assert result["success"] is True
        assert result["tag"].endswith("-abc1234")
        assert result["tag"].startswith("v3.")

    def test_default_tag_falls_back_to_local_when_git_fails(self, acr_settings, monkeypatch):
        def fake_run(cmd, **kwargs):
            if cmd[:2] == ["git", "rev-parse"]:
                raise OSError("git not available")
            return _proc(returncode=0)

        monkeypatch.setattr(subprocess, "run", fake_run)

        result = acr_build(acr_settings, repo_path="/tmp/repo", image_name="img")

        assert result["tag"].endswith("-local")

    def test_no_push_skips_docker_push(self, acr_settings, monkeypatch):
        calls: list[list[str]] = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            return _proc(returncode=0)

        monkeypatch.setattr(subprocess, "run", fake_run)

        result = acr_build(
            acr_settings, repo_path="/tmp/repo", image_name="img", tag="v1", push=False
        )

        assert result["pushed"] is False
        assert "push" not in [c[1] for c in calls]

    def test_docker_login_failure(self, acr_settings, monkeypatch):
        def fake_run(cmd, **kwargs):
            return _proc(returncode=1, stderr="unauthorized")

        monkeypatch.setattr(subprocess, "run", fake_run)

        result = acr_build(acr_settings, repo_path="/tmp/repo", image_name="img", tag="v1")

        assert result["error"] == "DockerLoginError"
        assert "unauthorized" in result["details"]

    def test_docker_not_found(self, acr_settings, monkeypatch):
        def fake_run(cmd, **kwargs):
            raise FileNotFoundError("docker")

        monkeypatch.setattr(subprocess, "run", fake_run)

        result = acr_build(acr_settings, repo_path="/tmp/repo", image_name="img", tag="v1")

        assert result["error"] == "DockerNotFound"

    def test_docker_login_timeout(self, acr_settings, monkeypatch):
        def fake_run(cmd, **kwargs):
            raise subprocess.TimeoutExpired(cmd="docker login", timeout=30)

        monkeypatch.setattr(subprocess, "run", fake_run)

        result = acr_build(acr_settings, repo_path="/tmp/repo", image_name="img", tag="v1")

        assert result["error"] == "Timeout"

    def test_docker_build_failure(self, acr_settings, monkeypatch):
        def fake_run(cmd, **kwargs):
            if cmd[1] == "build":
                return _proc(returncode=1, stderr="build blew up")
            return _proc(returncode=0)

        monkeypatch.setattr(subprocess, "run", fake_run)

        result = acr_build(acr_settings, repo_path="/tmp/repo", image_name="img", tag="v1")

        assert result["error"] == "DockerBuildError"
        assert "build blew up" in result["details"]

    def test_docker_build_timeout(self, acr_settings, monkeypatch):
        def fake_run(cmd, **kwargs):
            if cmd[1] == "build":
                raise subprocess.TimeoutExpired(cmd="docker build", timeout=600)
            return _proc(returncode=0)

        monkeypatch.setattr(subprocess, "run", fake_run)

        result = acr_build(acr_settings, repo_path="/tmp/repo", image_name="img", tag="v1")

        assert result["error"] == "Timeout"
        assert "build" in result["details"]

    def test_docker_push_failure(self, acr_settings, monkeypatch):
        def fake_run(cmd, **kwargs):
            if cmd[1] == "push":
                return _proc(returncode=1, stderr="push denied")
            return _proc(returncode=0)

        monkeypatch.setattr(subprocess, "run", fake_run)

        result = acr_build(acr_settings, repo_path="/tmp/repo", image_name="img", tag="v1")

        assert result["error"] == "DockerPushError"
        assert "push denied" in result["details"]

    def test_docker_push_timeout(self, acr_settings, monkeypatch):
        def fake_run(cmd, **kwargs):
            if cmd[1] == "push":
                raise subprocess.TimeoutExpired(cmd="docker push", timeout=300)
            return _proc(returncode=0)

        monkeypatch.setattr(subprocess, "run", fake_run)

        result = acr_build(acr_settings, repo_path="/tmp/repo", image_name="img", tag="v1")

        assert result["error"] == "Timeout"


# ─────────────────────────────────────────────────────────────────────────── #
# list_acr_images                                                               #
# ─────────────────────────────────────────────────────────────────────────── #
class TestListAcrImages:
    def test_missing_credentials_returns_config_error(self, client, no_acr_settings):
        result = list_acr_images(client, no_acr_settings, service_name="svc")
        assert result["error"] == "ConfigError"

    def test_returns_tags(self, client, acr_settings):
        client.list_acr_tags = MagicMock(
            return_value=[
                {"name": "v3.1", "digest": "sha256:aaa"},
                {"name": "v3.0", "digest": "sha256:bbb"},
            ]
        )

        result = list_acr_images(client, acr_settings, service_name="platform-x", limit=5)

        assert result["count"] == 2
        assert result["service"] == "platform-x"
        assert result["image"] == "test.azurecr.io/test/3.0/platform-x"
        client.list_acr_tags.assert_called_once()

    def test_client_error_returns_error_dict(self, client, acr_settings):
        client.list_acr_tags = MagicMock(side_effect=GitHubClientError("acr down"))

        result = list_acr_images(client, acr_settings, service_name="svc")

        assert result["error"] == "GitHubClientError"
        assert result["tool"] == "list_acr_images"
