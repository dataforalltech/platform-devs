"""Coleta de contexto de ambiente (git/OS) — sem banco.

Exercita ``collect_environment_context`` (cache TTL de 60s) e ``_collect_fresh``
(ramos git: sucesso / returncode != 0 / exceção, e o bloco OS). Não toca MySQL nem
o SessionManager singleton — apenas monkeypatch de ``subprocess.run`` e dos globais
de cache do módulo."""

from __future__ import annotations

import subprocess
from typing import Any

import src.knowledge.session as session_mod
from src.knowledge.session import _collect_fresh, collect_environment_context


class _FakeProc:
    """Stand-in mínimo de ``subprocess.CompletedProcess`` (só returncode + stdout)."""

    def __init__(self, returncode: int, stdout: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout


def _git_ok(args: list[str], **_kwargs: Any) -> _FakeProc:
    """Simula git presente respondendo a cada `git rev-parse ...` por flag."""
    if "--abbrev-ref" in args:
        return _FakeProc(0, "feat/env\n")
    if "--show-toplevel" in args:
        return _FakeProc(0, "/home/dev/platform-devs\n")
    if "--short=7" in args:
        return _FakeProc(0, "abc1234\n")
    return _FakeProc(1, "")


def _git_fail(*_args: Any, **_kwargs: Any) -> _FakeProc:
    """Simula git respondendo returncode != 0 (repo ausente / erro)."""
    return _FakeProc(1, "")


def _reset_cache(monkeypatch: Any) -> None:
    monkeypatch.setattr(session_mod, "_context_cache", None)
    monkeypatch.setattr(session_mod, "_context_cached_at", 0.0)


# ── _collect_fresh (git + OS) ──────────────────────────────────────────────────
class TestCollectFresh:
    def test_git_success_populates_all_fields(self, monkeypatch):
        monkeypatch.setattr(session_mod.subprocess, "run", _git_ok)
        ctx = _collect_fresh()
        assert ctx["git"]["branch"] == "feat/env"
        assert ctx["git"]["repo"] == "platform-devs"
        assert ctx["git"]["repo_path"] == "/home/dev/platform-devs"
        assert ctx["git"]["head_sha"] == "abc1234"
        # bloco OS é sempre coletado
        assert set(ctx["os"]) == {"system", "hostname", "python", "cwd", "user"}
        assert "captured_at" in ctx

    def test_git_nonzero_returncode_leaves_git_empty(self, monkeypatch):
        monkeypatch.setattr(session_mod.subprocess, "run", _git_fail)
        ctx = _collect_fresh()
        assert ctx["git"] == {}
        # OS ainda é coletado mesmo sem git
        assert ctx["os"]["system"]

    def test_git_exception_is_swallowed(self, monkeypatch):
        def _boom(*_a: Any, **_k: Any) -> _FakeProc:
            raise subprocess.SubprocessError("git indisponível")

        monkeypatch.setattr(session_mod.subprocess, "run", _boom)
        ctx = _collect_fresh()
        assert ctx["git"] == {}
        assert ctx["os"]["python"]

    def test_os_user_falls_back_to_unknown(self, monkeypatch):
        monkeypatch.setattr(session_mod.subprocess, "run", _git_fail)
        monkeypatch.delenv("USER", raising=False)
        monkeypatch.delenv("USERNAME", raising=False)
        ctx = _collect_fresh()
        assert ctx["os"]["user"] == "unknown"


# ── collect_environment_context (cache TTL) ────────────────────────────────────
class TestCollectEnvironmentContext:
    def test_force_true_collects_and_populates_cache(self, monkeypatch):
        _reset_cache(monkeypatch)
        monkeypatch.setattr(session_mod.subprocess, "run", _git_ok)
        ctx = collect_environment_context(force=True)
        assert ctx["git"]["branch"] == "feat/env"
        assert session_mod._context_cache is ctx

    def test_second_call_within_ttl_returns_cached_object(self, monkeypatch):
        _reset_cache(monkeypatch)
        monkeypatch.setattr(session_mod.subprocess, "run", _git_ok)
        first = collect_environment_context(force=True)

        def _must_not_recollect(*_a: Any, **_k: Any) -> _FakeProc:
            raise AssertionError("não deveria recoletar dentro do TTL")

        monkeypatch.setattr(session_mod.subprocess, "run", _must_not_recollect)
        second = collect_environment_context(force=False)
        assert second is first

    def test_expired_cache_recollects(self, monkeypatch):
        _reset_cache(monkeypatch)
        monkeypatch.setattr(session_mod.subprocess, "run", _git_ok)
        first = collect_environment_context(force=True)
        # empurra o timestamp p/ além do TTL → próxima chamada recoleta
        monkeypatch.setattr(
            session_mod,
            "_context_cached_at",
            session_mod.time.monotonic() - session_mod._CONTEXT_TTL - 1,
        )
        second = collect_environment_context(force=False)
        assert second is not first
        assert second["git"]["branch"] == "feat/env"
