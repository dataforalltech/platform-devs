"""Testes para DeploySettings — resolução de repos_root."""

from __future__ import annotations

from pathlib import Path

from src.config.settings import DeploySettings


def _settings(**kwargs) -> DeploySettings:
    base = {"github_token": "t", "github_org": "test-org"}
    base.update(kwargs)
    return DeploySettings(**base)


def test_repos_root_path_from_field(tmp_path):
    s = _settings(repos_root=str(tmp_path))
    assert s.get_repos_root_path() == tmp_path.resolve()


def test_repos_root_path_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("REPOS_ROOT", str(tmp_path))
    s = _settings(repos_root="")
    assert s.get_repos_root_path() == tmp_path.resolve()


def test_repos_root_path_from_workspace_env(tmp_path, monkeypatch):
    monkeypatch.delenv("REPOS_ROOT", raising=False)
    monkeypatch.setenv("WORKSPACE_REPOS_ROOT", str(tmp_path))
    s = _settings(repos_root="")
    assert s.get_repos_root_path() == tmp_path.resolve()


def test_repos_root_path_none_when_unset(monkeypatch):
    monkeypatch.delenv("REPOS_ROOT", raising=False)
    monkeypatch.delenv("WORKSPACE_REPOS_ROOT", raising=False)
    s = _settings(repos_root="")
    assert s.get_repos_root_path() is None


def test_defaults():
    s = _settings()
    assert s.github_org == "test-org"
    assert s.acr_registry == "d4all.azurecr.io"
    assert s.default_base_branch == "develop"
    assert isinstance(s.get_repos_root_path(), (Path, type(None)))
