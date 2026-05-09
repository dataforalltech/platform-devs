"""Testes para tools de Git: list_repos, create_branch, list_branches, commit_files."""

from __future__ import annotations

from unittest.mock import MagicMock

from github.GithubException import UnknownObjectException

from src.tools.git_tool import commit_files, create_branch, list_branches, list_repos

from .conftest import make_mock_repo


class TestListRepos:
    def test_returns_repos_list(self, client, mock_github):
        mock_org = MagicMock()
        mock_github.get_organization.return_value = mock_org
        mock_org.get_repos.return_value = [
            make_mock_repo("platform-analytics"),
            make_mock_repo("platform-core"),
        ]

        result = list_repos(client)

        assert "repos" in result
        assert result["count"] == 2
        assert result["repos"][0]["name"] == "platform-analytics"

    def test_filter_by_name(self, client, mock_github):
        mock_org = MagicMock()
        mock_github.get_organization.return_value = mock_org
        r1 = make_mock_repo("platform-analytics")
        r2 = make_mock_repo("platform-core")
        r3 = make_mock_repo("dataforall-backend")
        mock_org.get_repos.return_value = [r1, r2, r3]

        result = list_repos(client, filter_name="platform")

        assert result["count"] == 2
        names = [r["name"] for r in result["repos"]]
        assert "dataforall-backend" not in names

    def test_excludes_archived_by_default(self, client, mock_github):
        mock_org = MagicMock()
        mock_github.get_organization.return_value = mock_org
        active = make_mock_repo("active-repo")
        archived = make_mock_repo("archived-repo")
        archived.archived = True
        mock_org.get_repos.return_value = [active, archived]

        result = list_repos(client)

        assert result["count"] == 1
        assert result["repos"][0]["name"] == "active-repo"

    def test_error_returns_dict_with_error_key(self, client, mock_github):
        from github import GithubException

        mock_github.get_organization.side_effect = GithubException(403, "Forbidden")

        result = list_repos(client)

        assert "error" in result
        assert result["tool"] == "list_repos"


class TestCreateBranch:
    def test_creates_branch_from_develop(self, client, mock_github):
        mock_repo = make_mock_repo()
        mock_github.get_repo.return_value = mock_repo
        mock_branch = MagicMock()
        mock_branch.commit.sha = "deadbeef"
        mock_repo.get_branch.return_value = mock_branch

        result = create_branch(client, "my-repo", "feature/test-123", "develop")

        mock_repo.create_git_ref.assert_called_once_with(
            ref="refs/heads/feature/test-123", sha="deadbeef"
        )
        assert result["branch"] == "feature/test-123"
        assert result["sha"] == "deadbeef"

    def test_missing_repo_returns_validation_error(self, client):
        result = create_branch(client, "", "feature/x", "develop")
        assert result["error"] == "ValidationError"

    def test_branch_already_exists_returns_error(self, client, mock_github):
        from github import GithubException

        mock_repo = make_mock_repo()
        mock_github.get_repo.return_value = mock_repo
        mock_branch = MagicMock()
        mock_branch.commit.sha = "abc123"
        mock_repo.get_branch.return_value = mock_branch
        mock_repo.create_git_ref.side_effect = GithubException(422, "Reference already exists")

        result = create_branch(client, "my-repo", "feature/exists", "develop")

        assert "error" in result
        assert "já existe" in result["details"]

    def test_resolves_sha_when_branch_not_found(self, client, mock_github):
        from github import GithubException

        mock_repo = make_mock_repo()
        mock_github.get_repo.return_value = mock_repo
        # get_branch falha → tenta como SHA
        mock_repo.get_branch.side_effect = GithubException(404, "Not Found")
        mock_commit = MagicMock()
        mock_commit.sha = "sha123abc"
        mock_repo.get_commit.return_value = mock_commit

        result = create_branch(client, "my-repo", "feature/from-sha", "sha123abc")

        assert result["sha"] == "sha123abc"


class TestListBranches:
    def test_returns_branches(self, client, mock_github):
        mock_repo = make_mock_repo()
        mock_github.get_repo.return_value = mock_repo
        b1 = MagicMock()
        b1.name = "develop"
        b1.commit.sha = "aaa"
        b1.protected = True
        b2 = MagicMock()
        b2.name = "feature/x"
        b2.commit.sha = "bbb"
        b2.protected = False
        mock_repo.get_branches.return_value = [b1, b2]

        result = list_branches(client, "my-repo")

        assert result["count"] == 2
        assert result["branches"][0]["name"] == "develop"
        assert result["branches"][0]["protected"] is True

    def test_filter_by_prefix(self, client, mock_github):
        mock_repo = make_mock_repo()
        mock_github.get_repo.return_value = mock_repo
        b1 = MagicMock()
        b1.name = "develop"
        b1.commit.sha = "aaa"
        b1.protected = True
        b2 = MagicMock()
        b2.name = "feature/x"
        b2.commit.sha = "bbb"
        b2.protected = False
        mock_repo.get_branches.return_value = [b1, b2]

        result = list_branches(client, "my-repo", filter_name="feature")

        assert result["count"] == 1
        assert result["branches"][0]["name"] == "feature/x"


class TestCommitFiles:
    def test_single_file_create(self, client, mock_github):
        mock_repo = make_mock_repo()
        mock_github.get_repo.return_value = mock_repo
        # Arquivo não existe ainda
        mock_repo.get_contents.side_effect = UnknownObjectException(404, "Not Found")
        mock_commit = MagicMock()
        mock_commit.sha = "commit_sha_abc"
        mock_commit.html_url = "https://github.com/test-org/my-repo/commit/commit_sha_abc"
        mock_repo.create_file.return_value = {"commit": mock_commit, "content": MagicMock()}

        result = commit_files(
            client,
            repo="my-repo",
            branch="feature/test",
            message="feat: add file",
            files=[{"path": "src/hello.py", "content": "print('hello')"}],
        )

        mock_repo.create_file.assert_called_once()
        assert result["sha"] == "commit_sha_abc"
        assert "src/hello.py" in result["files"]

    def test_single_file_update(self, client, mock_github):
        mock_repo = make_mock_repo()
        mock_github.get_repo.return_value = mock_repo
        existing = MagicMock()
        existing.sha = "existing_blob_sha"
        mock_repo.get_contents.return_value = existing
        mock_commit = MagicMock()
        mock_commit.sha = "new_sha"
        mock_commit.html_url = "https://github.com/test-org/my-repo/commit/new_sha"
        mock_repo.update_file.return_value = {"commit": mock_commit, "content": MagicMock()}

        result = commit_files(
            client,
            repo="my-repo",
            branch="develop",
            message="chore: update config",
            files=[{"path": "config.yml", "content": "key: value"}],
        )

        mock_repo.update_file.assert_called_once()
        assert result["sha"] == "new_sha"

    def test_empty_files_returns_validation_error(self, client):
        result = commit_files(client, "repo", "branch", "msg", [])
        assert result["error"] == "ValidationError"

    def test_files_missing_path_returns_validation_error(self, client):
        result = commit_files(
            client, "repo", "branch", "msg", [{"content": "x"}]
        )
        assert result["error"] == "ValidationError"

    def test_multiple_files_uses_git_data_api(self, client, mock_github):
        mock_repo = make_mock_repo()
        mock_github.get_repo.return_value = mock_repo

        mock_ref = MagicMock()
        mock_ref.object.sha = "base_sha"
        mock_repo.get_git_ref.return_value = mock_ref

        mock_parent = MagicMock()
        mock_parent.tree = MagicMock()
        mock_repo.get_git_commit.return_value = mock_parent

        mock_blob = MagicMock()
        mock_blob.sha = "blob_sha"
        mock_repo.create_git_blob.return_value = mock_blob

        mock_tree = MagicMock()
        mock_repo.create_git_tree.return_value = mock_tree

        mock_commit = MagicMock()
        mock_commit.sha = "multi_commit_sha"
        mock_commit.html_url = "https://github.com/test-org/my-repo/commit/multi_commit_sha"
        mock_repo.create_git_commit.return_value = mock_commit

        result = commit_files(
            client,
            repo="my-repo",
            branch="feature/multi",
            message="feat: add multiple files",
            files=[
                {"path": "a.py", "content": "# a"},
                {"path": "b.py", "content": "# b"},
                {"path": "c.py", "content": "# c"},
            ],
        )

        assert mock_repo.create_git_blob.call_count == 3
        mock_ref.edit.assert_called_once_with("multi_commit_sha")
        assert result["sha"] == "multi_commit_sha"
        assert len(result["files"]) == 3
