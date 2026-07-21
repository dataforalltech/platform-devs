"""Testes do clone-or-pull idempotente (ADR-017 Fatia C — deploy.sync_repo).

Pura-git, sem rede/MySQL: usa um "remote" local (bare repo) e prova as 3 rotas do
pull idempotente (pulled / up-to-date no-op / skipped_dirty). A rota de clone (destino
ausente) delega ao clone_repo já existente e não é reexercitada aqui.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from src.domains.deploy.tools.local_tool import sync_repo

_GIT = shutil.which("git") or "git"  # caminho absoluto evita S607 (partial path)
_GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
}
_SETTINGS = SimpleNamespace(github_org="test-org", github_token="")


def _git(cwd, *args: str) -> str:
    r = subprocess.run(  # noqa: S603 — args de git controlados pelo teste
        [_GIT, *args], cwd=str(cwd), capture_output=True, text=True, env=_GIT_ENV
    )
    assert r.returncode == 0, f"git {' '.join(args)} -> {r.stderr}"
    return r.stdout.strip()


@pytest.fixture
def workspace(tmp_path):
    remote = tmp_path / "remote.git"
    _git(tmp_path, "init", "--bare", "-b", "main", str(remote))
    seed = tmp_path / "seed"
    _git(tmp_path, "clone", str(remote), str(seed))
    (seed / "README.md").write_text("v1", encoding="utf-8")
    _git(seed, "add", ".")
    _git(seed, "commit", "-m", "init")
    _git(seed, "push", "origin", "HEAD:main")
    root = tmp_path / "repos"
    root.mkdir()
    _git(root, "clone", str(remote), "myrepo")
    return root, seed


def test_sync_repo_pulls_new_upstream_commit(workspace):
    root, seed = workspace
    (seed / "f2.txt").write_text("v2", encoding="utf-8")
    _git(seed, "add", ".")
    _git(seed, "commit", "-m", "second")
    _git(seed, "push", "origin", "HEAD:main")

    out = sync_repo(None, _SETTINGS, repo="myrepo", repos_root=str(root))
    assert out["action"] == "pulled", out
    assert (root / "myrepo" / "f2.txt").exists()


def test_sync_repo_is_idempotent_when_up_to_date(workspace):
    root, _ = workspace
    first = sync_repo(None, _SETTINGS, repo="myrepo", repos_root=str(root))
    assert first["action"] == "pulled", first
    second = sync_repo(None, _SETTINGS, repo="myrepo", repos_root=str(root))
    assert second["action"] == "pulled", second  # ff no-op, sem erro


def test_sync_repo_skips_and_preserves_dirty_worktree(workspace):
    root, _ = workspace
    dirty = root / "myrepo" / "README.md"
    dirty.write_text("mudança local não commitada", encoding="utf-8")
    out = sync_repo(None, _SETTINGS, repo="myrepo", repos_root=str(root))
    assert out["action"] == "skipped_dirty", out
    assert dirty.read_text(encoding="utf-8") == "mudança local não commitada"  # trabalho preservado
