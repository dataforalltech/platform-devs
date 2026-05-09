"""Testes para tools de PR: create_pr, get_pr, merge_pr, list_prs."""

from __future__ import annotations

from unittest.mock import MagicMock

from src.tools.pr_tool import create_pr, get_pr, list_prs, merge_pr

from .conftest import make_mock_pr, make_mock_repo


class TestCreatePR:
    def test_creates_pr_successfully(self, client, mock_github):
        mock_repo = make_mock_repo()
        mock_github.get_repo.return_value = mock_repo
        mock_pr = make_mock_pr(number=10, title="feat: new feature")
        mock_repo.create_pull.return_value = mock_pr

        result = create_pr(
            client,
            repo="my-repo",
            title="feat: new feature",
            body="Descrição do PR",
            head="feature/new-feat",
        )

        mock_repo.create_pull.assert_called_once_with(
            title="feat: new feature",
            body="Descrição do PR",
            head="feature/new-feat",
            base="develop",
            draft=False,
        )
        assert result["number"] == 10
        assert result["url"].startswith("https://github.com")

    def test_uses_default_base_branch(self, client, mock_github):
        mock_repo = make_mock_repo()
        mock_github.get_repo.return_value = mock_repo
        mock_pr = make_mock_pr()
        mock_repo.create_pull.return_value = mock_pr

        create_pr(client, repo="my-repo", title="T", body="B", head="feature/x")

        call_kwargs = mock_repo.create_pull.call_args.kwargs
        assert call_kwargs["base"] == "develop"  # DEPLOY_DEFAULT_BASE_BRANCH

    def test_custom_base_branch(self, client, mock_github):
        mock_repo = make_mock_repo()
        mock_github.get_repo.return_value = mock_repo
        mock_pr = make_mock_pr()
        mock_repo.create_pull.return_value = mock_pr

        create_pr(
            client,
            repo="my-repo",
            title="fix: hotfix",
            body="B",
            head="hotfix/x",
            base="main",
        )

        call_kwargs = mock_repo.create_pull.call_args.kwargs
        assert call_kwargs["base"] == "main"

    def test_sets_labels_when_provided(self, client, mock_github):
        mock_repo = make_mock_repo()
        mock_github.get_repo.return_value = mock_repo
        mock_pr = make_mock_pr()
        mock_repo.create_pull.return_value = mock_pr

        create_pr(
            client,
            repo="my-repo",
            title="T",
            body="B",
            head="feature/x",
            labels=["bug", "priority:high"],
        )

        mock_pr.set_labels.assert_called_once_with("bug", "priority:high")

    def test_missing_required_fields_returns_validation_error(self, client):
        result = create_pr(client, repo="", title="T", body="B", head="feature/x")
        assert result["error"] == "ValidationError"

    def test_github_error_returns_error_dict(self, client, mock_github):
        from github import GithubException

        mock_repo = make_mock_repo()
        mock_github.get_repo.return_value = mock_repo
        mock_repo.create_pull.side_effect = GithubException(422, "Validation Failed")

        result = create_pr(client, repo="my-repo", title="T", body="B", head="feature/x")

        assert "error" in result
        assert result["tool"] == "create_pr"


class TestGetPR:
    def test_returns_pr_details(self, client, mock_github):
        mock_repo = make_mock_repo()
        mock_github.get_repo.return_value = mock_repo
        mock_pr = make_mock_pr(number=42, title="feat: test")
        # Mock commits para check runs
        mock_commits_pager = MagicMock()
        mock_commits_pager.reversed = iter([MagicMock()])
        mock_pr.get_commits.return_value = mock_commits_pager
        mock_repo.get_pull.return_value = mock_pr

        result = get_pr(client, repo="my-repo", pr_number=42)

        assert result["number"] == 42
        assert result["title"] == "feat: test"
        assert "checks" in result
        assert "mergeable" in result

    def test_not_found_returns_error(self, client, mock_github):
        from github.GithubException import UnknownObjectException

        mock_repo = make_mock_repo()
        mock_github.get_repo.return_value = mock_repo
        mock_repo.get_pull.side_effect = UnknownObjectException(404, "Not Found")

        result = get_pr(client, repo="my-repo", pr_number=999)

        assert "error" in result
        assert "não encontrado" in result["details"]

    def test_missing_params_returns_validation_error(self, client):
        result = get_pr(client, repo="", pr_number=0)
        assert result["error"] == "ValidationError"


class TestMergePR:
    def test_merges_with_squash_default(self, client, mock_github):
        mock_repo = make_mock_repo()
        mock_github.get_repo.return_value = mock_repo
        mock_pr = make_mock_pr()
        mock_repo.get_pull.return_value = mock_pr
        mock_result = MagicMock()
        mock_result.merged = True
        mock_result.sha = "merged_sha"
        mock_result.message = "PR merged"
        mock_pr.merge.return_value = mock_result

        result = merge_pr(client, repo="my-repo", pr_number=42)

        mock_pr.merge.assert_called_once_with(merge_method="squash")
        assert result["merged"] is True
        assert result["sha"] == "merged_sha"

    def test_merge_rebase_method(self, client, mock_github):
        mock_repo = make_mock_repo()
        mock_github.get_repo.return_value = mock_repo
        mock_pr = make_mock_pr()
        mock_repo.get_pull.return_value = mock_pr
        mock_result = MagicMock()
        mock_result.merged = True
        mock_result.sha = "sha"
        mock_result.message = ""
        mock_pr.merge.return_value = mock_result

        merge_pr(client, repo="my-repo", pr_number=42, method="rebase")

        mock_pr.merge.assert_called_once_with(merge_method="rebase")

    def test_invalid_method_returns_validation_error(self, client):
        result = merge_pr(client, repo="my-repo", pr_number=42, method="invalid")
        assert result["error"] == "ValidationError"
        assert "method inválido" in result["details"]

    def test_pr_not_found_returns_error(self, client, mock_github):
        from github.GithubException import UnknownObjectException

        mock_repo = make_mock_repo()
        mock_github.get_repo.return_value = mock_repo
        mock_repo.get_pull.side_effect = UnknownObjectException(404, "Not Found")

        result = merge_pr(client, repo="my-repo", pr_number=9999)

        assert "error" in result


class TestListPRs:
    def test_returns_open_prs(self, client, mock_github):
        mock_repo = make_mock_repo()
        mock_github.get_repo.return_value = mock_repo
        prs = [make_mock_pr(i) for i in range(1, 4)]
        mock_repo.get_pulls.return_value = prs

        result = list_prs(client, repo="my-repo")

        assert result["count"] == 3
        mock_repo.get_pulls.assert_called_with(state="open")

    def test_filter_by_author(self, client, mock_github):
        mock_repo = make_mock_repo()
        mock_github.get_repo.return_value = mock_repo
        pr1 = make_mock_pr(1)
        pr1.user.login = "alice"
        pr2 = make_mock_pr(2)
        pr2.user.login = "bob"
        mock_repo.get_pulls.return_value = [pr1, pr2]

        result = list_prs(client, repo="my-repo", author="alice")

        assert result["count"] == 1
        assert result["prs"][0]["number"] == 1

    def test_invalid_state_returns_validation_error(self, client):
        result = list_prs(client, repo="my-repo", state="invalid")
        assert result["error"] == "ValidationError"

    def test_missing_repo_returns_validation_error(self, client):
        result = list_prs(client, repo="")
        assert result["error"] == "ValidationError"
