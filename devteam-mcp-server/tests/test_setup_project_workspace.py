"""Testes de `setup_project_workspace` (ADR-017 D17.9, escopo PARCIAL —
`deploy.setup_project_workspace`).

Pura-git, sem rede/MySQL: mesmo padrão de `test_sync_repo.py` (remote local bare),
com DOIS repos para provar que a orquestração agrega resultados corretamente e não
para no primeiro erro.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from src.domains.deploy.tools.local_tool import setup_project_workspace

_GIT = shutil.which("git") or "git"
_GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@t",
}
_SETTINGS = SimpleNamespace(github_org="test-org", github_token="")


def _git(cwd, *args: str) -> str:
    r = subprocess.run(  # noqa: S603 — args de git controlados pelo teste
        [_GIT, *args], cwd=str(cwd), capture_output=True, text=True, env=_GIT_ENV
    )
    assert r.returncode == 0, f"git {' '.join(args)} -> {r.stderr}"
    return r.stdout.strip()


def _make_repo(tmp_path, root, name: str):
    remote = tmp_path / f"{name}.git"
    _git(tmp_path, "init", "--bare", "-b", "main", str(remote))
    seed = tmp_path / f"seed-{name}"
    _git(tmp_path, "clone", str(remote), str(seed))
    (seed / "README.md").write_text("v1", encoding="utf-8")
    _git(seed, "add", ".")
    _git(seed, "commit", "-m", "init")
    _git(seed, "push", "origin", "HEAD:main")
    _git(root, "clone", str(remote), name)
    return seed


@pytest.fixture
def two_repo_workspace(tmp_path):
    root = tmp_path / "repos"
    root.mkdir()
    seed_a = _make_repo(tmp_path, root, "repo-a")
    seed_b = _make_repo(tmp_path, root, "repo-b")
    return root, seed_a, seed_b


def test_setup_project_workspace_syncs_all_repos(two_repo_workspace):
    root, seed_a, seed_b = two_repo_workspace
    (seed_a / "f2.txt").write_text("v2", encoding="utf-8")
    _git(seed_a, "add", ".")
    _git(seed_a, "commit", "-m", "second")
    _git(seed_a, "push", "origin", "HEAD:main")

    out = setup_project_workspace(
        None,
        _SETTINGS,
        project_id="proj-1",
        repos=[{"repo": "repo-a"}, {"repo": "repo-b"}],
        repos_root=str(root),
    )
    assert out["total"] == 2
    assert out["ok"] == 2
    assert out["skipped"] == 0
    assert out["errored"] == 0
    assert (root / "repo-a" / "f2.txt").exists()


def test_setup_project_workspace_does_not_stop_on_dirty_worktree(
    two_repo_workspace,
):
    root, seed_a, _seed_b = two_repo_workspace
    dirty = root / "repo-a" / "README.md"
    dirty.write_text("mudança local não commitada", encoding="utf-8")

    out = setup_project_workspace(
        None,
        _SETTINGS,
        project_id="proj-1",
        repos=[{"repo": "repo-a"}, {"repo": "repo-b"}],
        repos_root=str(root),
    )
    # repo-a fica sujo (skipped_dirty), mas repo-b ainda é sincronizado.
    assert out["total"] == 2
    assert out["skipped"] == 1
    assert out["ok"] == 1
    assert dirty.read_text(encoding="utf-8") == "mudança local não commitada"

    by_repo = {r["repo"].split("/")[-1]: r for r in out["results"]}
    assert by_repo["repo-a"]["action"] == "skipped_dirty"
    assert by_repo["repo-b"]["action"] == "pulled"


def test_setup_project_workspace_requires_non_empty_repos():
    out = setup_project_workspace(None, _SETTINGS, project_id="proj-1", repos=[])
    assert "error" in out


def test_setup_project_workspace_flags_entry_without_repo_field(
    two_repo_workspace,
):
    root, _seed_a, _seed_b = two_repo_workspace
    out = setup_project_workspace(
        None,
        _SETTINGS,
        project_id="proj-1",
        repos=[{"branch": "main"}, {"repo": "repo-b"}],
        repos_root=str(root),
    )
    assert out["total"] == 2
    assert out["errored"] == 1
    assert out["ok"] == 1
    assert "error" in out["results"][0]
