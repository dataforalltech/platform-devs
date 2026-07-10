"""Testes para tools de workspace local: get_repos_root, set_repos_root,
list_local_repos, clone_repo.

git/subprocess são mockados; o filesystem usa tmp_path (isolado). Nada roda de verdade.
"""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock

import pytest

from src.config.settings import DeploySettings
from src.tools import local_tool
from src.tools.local_tool import (
    _git_info,
    _resolve_repos_root,
    clone_repo,
    get_repos_root,
    list_local_repos,
    set_repos_root,
)


@pytest.fixture
def settings_with_root(tmp_path) -> DeploySettings:
    return DeploySettings(
        github_token="test_token",
        github_org="test-org",
        repos_root=str(tmp_path),
    )


def _make_git_repo(root, name: str):
    """Cria um diretório com .git para simular um repo clonado."""
    repo = root / name
    (repo / ".git").mkdir(parents=True)
    return repo


# ─────────────────────────────────────────────────────────────────────────── #
# _resolve_repos_root                                                           #
# ─────────────────────────────────────────────────────────────────────────── #
class TestResolveReposRoot:
    def test_explicit_wins(self, settings, tmp_path):
        resolved = _resolve_repos_root(settings, explicit=str(tmp_path))
        assert resolved == tmp_path.resolve()

    def test_from_settings(self, settings_with_root, tmp_path):
        resolved = _resolve_repos_root(settings_with_root)
        assert resolved == tmp_path.resolve()

    def test_returns_none_when_nothing_configured(self, settings, monkeypatch):
        # Sem settings.repos_root, sem env vars, sem config-mcp, sem auto-detect
        monkeypatch.delenv("REPOS_ROOT", raising=False)
        monkeypatch.delenv("WORKSPACE_REPOS_ROOT", raising=False)
        # Força config-mcp import a falhar e auto-detect a não achar nada
        monkeypatch.setattr(local_tool, "_AUTO_DETECT_CANDIDATES", ["/definitely/not/here/xyz"])
        resolved = _resolve_repos_root(settings)
        assert resolved is None


# ─────────────────────────────────────────────────────────────────────────── #
# _git_info                                                                     #
# ─────────────────────────────────────────────────────────────────────────── #
class TestGitInfo:
    def test_collects_info_from_git(self, tmp_path, monkeypatch):
        outputs = {
            ("rev-parse", "--abbrev-ref", "HEAD"): "develop",
            ("remote", "get-url", "origin"): "https://github.com/test-org/x.git",
            ("log", "-1", "--format=%h %s (%ar)", "--no-merges"): "abc123 msg (2 days ago)",
            ("status", "--porcelain"): "",
            ("describe", "--tags", "--abbrev=0"): "v1.0.0",
        }

        def fake_run(cmd, **kwargs):
            key = tuple(cmd[1:])
            m = MagicMock()
            m.returncode = 0
            m.stdout = outputs.get(key, "")
            m.stderr = ""
            return m

        monkeypatch.setattr(subprocess, "run", fake_run)

        info = _git_info(tmp_path)
        assert info["branch"] == "develop"
        assert info["remote"] == "https://github.com/test-org/x.git"
        assert info["latest_tag"] == "v1.0.0"
        assert info["dirty"] is False

    def test_handles_git_not_found(self, tmp_path, monkeypatch):
        def fake_run(cmd, **kwargs):
            raise FileNotFoundError("git")

        monkeypatch.setattr(subprocess, "run", fake_run)

        info = _git_info(tmp_path)
        assert info["branch"] == "unknown"
        assert info["remote"] is None


# ─────────────────────────────────────────────────────────────────────────── #
# get_repos_root                                                                #
# ─────────────────────────────────────────────────────────────────────────── #
class TestGetReposRoot:
    def test_returns_resolved_root_and_counts_repos(self, settings_with_root, tmp_path):
        _make_git_repo(tmp_path, "repo-a")
        _make_git_repo(tmp_path, "repo-b")
        (tmp_path / "not-a-repo").mkdir()

        result = get_repos_root(settings_with_root)

        assert result["repos_root"] == str(tmp_path.resolve())
        assert result["exists"] is True
        assert result["repo_count"] == 2
        assert result["source"] == "DEPLOY_REPOS_ROOT"

    def test_explicit_source(self, settings, tmp_path):
        result = get_repos_root(settings, explicit=str(tmp_path))
        assert result["source"] == "argument"

    def test_not_configured_returns_tip(self, settings, monkeypatch):
        monkeypatch.setattr(local_tool, "_AUTO_DETECT_CANDIDATES", ["/nope/xyz"])
        monkeypatch.delenv("REPOS_ROOT", raising=False)
        monkeypatch.delenv("WORKSPACE_REPOS_ROOT", raising=False)

        result = get_repos_root(settings)
        assert result["repos_root"] is None
        assert "tip" in result


# ─────────────────────────────────────────────────────────────────────────── #
# set_repos_root                                                                #
# ─────────────────────────────────────────────────────────────────────────── #
class TestSetReposRoot:
    def test_existing_dir_no_persist(self, settings, tmp_path, monkeypatch):
        monkeypatch.setattr(local_tool, "_push_repos_root_to_config_mcp", lambda p: False)
        result = set_repos_root(settings, path=str(tmp_path), persist=False)
        assert result["repos_root"] == str(tmp_path.resolve())
        assert result["persisted_to_config_mcp"] is False

    def test_missing_dir_without_create_returns_error(self, settings, tmp_path):
        missing = tmp_path / "does-not-exist"
        result = set_repos_root(settings, path=str(missing), create_dir=False)
        assert "error" in result
        assert "create_dir=true" in result["tip"]

    def test_create_dir_creates_and_persists(self, settings, tmp_path, monkeypatch):
        monkeypatch.setattr(local_tool, "_push_repos_root_to_config_mcp", lambda p: True)
        new_dir = tmp_path / "new-workspace"
        result = set_repos_root(settings, path=str(new_dir), create_dir=True, persist=True)
        assert new_dir.exists()
        assert result["persisted_to_config_mcp"] is True

    def test_path_is_file_returns_error(self, settings, tmp_path):
        a_file = tmp_path / "file.txt"
        a_file.write_text("x")
        result = set_repos_root(settings, path=str(a_file), persist=False)
        assert "nao e um diretorio" in result["error"]


# ─────────────────────────────────────────────────────────────────────────── #
# list_local_repos                                                              #
# ─────────────────────────────────────────────────────────────────────────── #
class TestListLocalRepos:
    def test_lists_repos_with_git_info(self, settings_with_root, tmp_path, monkeypatch):
        _make_git_repo(tmp_path, "repo-a")
        (tmp_path / "plain-dir").mkdir()

        monkeypatch.setattr(
            local_tool,
            "_git_info",
            lambda p: {
                "branch": "main",
                "remote": None,
                "last_commit": None,
                "dirty": False,
                "latest_tag": None,
            },
        )

        result = list_local_repos(settings_with_root)

        assert result["total"] == 1
        assert result["repos"][0]["name"] == "repo-a"
        assert result["repos"][0]["branch"] == "main"
        assert "plain-dir" in result["non_repos_dirs"]

    def test_without_git_info_is_names_only(self, settings_with_root, tmp_path):
        _make_git_repo(tmp_path, "repo-a")
        result = list_local_repos(settings_with_root, include_git_info=False)
        assert result["repos"][0]["name"] == "repo-a"
        assert "branch" not in result["repos"][0]

    def test_filter_name(self, settings_with_root, tmp_path):
        _make_git_repo(tmp_path, "platform-auth")
        _make_git_repo(tmp_path, "other-svc")
        result = list_local_repos(settings_with_root, filter_name="platform", include_git_info=False)
        assert result["total"] == 1
        assert result["repos"][0]["name"] == "platform-auth"

    def test_root_not_configured(self, settings, monkeypatch):
        monkeypatch.setattr(local_tool, "_AUTO_DETECT_CANDIDATES", ["/nope/xyz"])
        monkeypatch.delenv("REPOS_ROOT", raising=False)
        monkeypatch.delenv("WORKSPACE_REPOS_ROOT", raising=False)
        result = list_local_repos(settings)
        assert "error" in result

    def test_root_does_not_exist(self, settings, tmp_path):
        missing = tmp_path / "missing"
        result = list_local_repos(settings, repos_root=str(missing))
        assert "error" in result


# ─────────────────────────────────────────────────────────────────────────── #
# clone_repo                                                                    #
# ─────────────────────────────────────────────────────────────────────────── #
class TestCloneRepo:
    def test_successful_clone(self, client, settings_with_root, tmp_path, monkeypatch):
        def fake_run(cmd, **kwargs):
            # simula git clone criando o destino
            dest = cmd[-1]
            import os

            os.makedirs(os.path.join(dest, ".git"), exist_ok=True)
            m = MagicMock()
            m.returncode = 0
            m.stdout = ""
            m.stderr = ""
            return m

        monkeypatch.setattr(subprocess, "run", fake_run)
        monkeypatch.setattr(
            local_tool,
            "_git_info",
            lambda p: {"branch": "develop", "last_commit": "abc msg"},
        )

        result = clone_repo(client, settings_with_root, repo="platform-auth")

        assert result["action"] == "cloned"
        assert result["repo"] == "test-org/platform-auth"
        # token não deve vazar no remote retornado
        assert "test_token" not in result["remote"]
        assert result["remote"] == "https://github.com/test-org/platform-auth.git"

    def test_accepts_owner_repo_form(self, client, settings_with_root, monkeypatch):
        def fake_run(cmd, **kwargs):
            dest = cmd[-1]
            import os

            os.makedirs(os.path.join(dest, ".git"), exist_ok=True)
            m = MagicMock()
            m.returncode = 0
            m.stdout = m.stderr = ""
            return m

        monkeypatch.setattr(subprocess, "run", fake_run)
        monkeypatch.setattr(local_tool, "_git_info", lambda p: {})

        result = clone_repo(client, settings_with_root, repo="acme/widget", depth=1, branch="main")
        assert result["repo"] == "acme/widget"

    def test_destination_exists_returns_error(self, client, settings_with_root, tmp_path):
        (tmp_path / "platform-auth").mkdir()
        result = clone_repo(client, settings_with_root, repo="platform-auth")
        assert "error" in result
        assert "ja existe" in result["error"]

    def test_clone_failure_redacts_token(self, client, settings_with_root, monkeypatch):
        def fake_run(cmd, **kwargs):
            m = MagicMock()
            m.returncode = 1
            m.stdout = ""
            m.stderr = "fatal: could not read from https://test_token@github.com/..."
            return m

        monkeypatch.setattr(subprocess, "run", fake_run)

        result = clone_repo(client, settings_with_root, repo="platform-auth")

        assert result["error"] == "git clone falhou"
        assert "test_token" not in result["details"]
        assert "***" in result["details"]

    def test_clone_timeout(self, client, settings_with_root, monkeypatch):
        def fake_run(cmd, **kwargs):
            raise subprocess.TimeoutExpired(cmd="git clone", timeout=120)

        monkeypatch.setattr(subprocess, "run", fake_run)

        result = clone_repo(client, settings_with_root, repo="platform-auth")
        assert "timeout" in result["error"]

    def test_git_not_found(self, client, settings_with_root, monkeypatch):
        def fake_run(cmd, **kwargs):
            raise FileNotFoundError("git")

        monkeypatch.setattr(subprocess, "run", fake_run)

        result = clone_repo(client, settings_with_root, repo="platform-auth")
        assert "git nao encontrado" in result["error"]

    def test_root_not_configured(self, client, settings, monkeypatch):
        monkeypatch.setattr(local_tool, "_AUTO_DETECT_CANDIDATES", ["/nope/xyz"])
        monkeypatch.delenv("REPOS_ROOT", raising=False)
        monkeypatch.delenv("WORKSPACE_REPOS_ROOT", raising=False)
        result = clone_repo(client, settings, repo="x")
        assert "error" in result
