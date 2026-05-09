"""Fixtures compartilhadas para todos os testes do deploy-mcp-server."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.config.settings import DeploySettings
from src.knowledge.github_client import GitHubClient


@pytest.fixture
def settings() -> DeploySettings:
    return DeploySettings(
        github_token="test_token_ghp_xxx",
        github_org="test-org",
        acr_registry="test.azurecr.io",
        acr_namespace="test/3.0",
        default_base_branch="develop",
    )


@pytest.fixture
def mock_github():
    """Patch Github() para evitar chamadas reais à API."""
    with patch("src.knowledge.github_client.Github") as mock_cls:
        mock_instance = MagicMock()
        mock_cls.return_value = mock_instance
        yield mock_instance


@pytest.fixture
def client(settings, mock_github) -> GitHubClient:
    """GitHubClient com Github mockado."""
    return GitHubClient(settings)


def make_mock_repo(
    name: str = "my-repo",
    default_branch: str = "develop",
    private: bool = True,
) -> MagicMock:
    repo = MagicMock()
    repo.name = name
    repo.full_name = f"test-org/{name}"
    repo.default_branch = default_branch
    repo.private = private
    repo.archived = False
    repo.html_url = f"https://github.com/test-org/{name}"
    return repo


def make_mock_pr(
    number: int = 42,
    title: str = "feat: test",
    state: str = "open",
    head_ref: str = "feature/test",
    base_ref: str = "develop",
    head_sha: str = "abc1234",
    draft: bool = False,
) -> MagicMock:
    pr = MagicMock()
    pr.number = number
    pr.title = title
    pr.state = state
    pr.html_url = f"https://github.com/test-org/my-repo/pull/{number}"
    pr.head.ref = head_ref
    pr.head.sha = head_sha
    pr.base.ref = base_ref
    pr.mergeable = True
    pr.mergeable_state = "clean"
    pr.draft = draft
    pr.user.login = "test-user"
    return pr


def make_mock_run(
    run_id: int = 12345,
    name: str = "CD DEV",
    status: str = "completed",
    conclusion: str = "success",
    head_branch: str = "develop",
    head_sha: str = "abc1234",
) -> MagicMock:
    from datetime import datetime

    run = MagicMock()
    run.id = run_id
    run.name = name
    run.status = status
    run.conclusion = conclusion
    run.head_branch = head_branch
    run.head_sha = head_sha
    run.created_at = datetime(2026, 5, 7, 10, 0, 0)
    run.updated_at = datetime(2026, 5, 7, 10, 5, 0)
    run.html_url = f"https://github.com/test-org/my-repo/actions/runs/{run_id}"
    run.logs_url = f"https://api.github.com/repos/test-org/my-repo/actions/runs/{run_id}/logs"
    return run
