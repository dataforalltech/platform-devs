"""Sessão autenticada em memória — singleton por processo.

Armazena o contexto do usuário autenticado na sessão atual.
Consumido por whoami(), get_twin_context() e pela HTTP API.

Thread-safety: todas as operações do SessionManager usam um RLock para evitar
race conditions entre a thread stdio do MCP e a thread HTTP do FastAPI.
"""
from __future__ import annotations

import logging
import os
import platform
import subprocess
import threading
import time
from dataclasses import dataclass, field, replace as dc_replace
from datetime import datetime, timezone
from typing import Any

_log = logging.getLogger(__name__)

# ── Context cache (module-level, TTL 60s) ────────────────────────────────── #
_context_cache: dict[str, Any] | None = None
_context_cached_at: float = 0.0
_context_lock = threading.Lock()
_CONTEXT_TTL = 60.0


@dataclass
class UserSession:
    token: str
    user_id: str
    name: str
    email: str
    role: str
    scopes: list[str]
    environment: str
    authenticated_at: str
    tenant_id: str | None = None
    context: dict[str, Any] = field(default_factory=dict)
    tool_calls: int = 0  # contador de tool calls desde autenticação


class SessionManager:
    """Singleton de sessão autenticada por processo MCP.

    Thread-safe: todas as operações são protegidas por RLock.
    """

    _current: UserSession | None = None
    _lock: threading.RLock = threading.RLock()

    @classmethod
    def set(cls, session: UserSession) -> None:
        with cls._lock:
            cls._current = session
        _log.info(
            "session_set user_id=%s name=%s environment=%s",
            session.user_id, session.name, session.environment,
        )

    @classmethod
    def get(cls) -> UserSession | None:
        with cls._lock:
            return cls._current

    @classmethod
    def clear(cls) -> None:
        with cls._lock:
            cls._current = None
        _log.info("session_cleared")

    @classmethod
    def is_authenticated(cls) -> bool:
        with cls._lock:
            return cls._current is not None

    @classmethod
    def require(cls) -> UserSession:
        with cls._lock:
            if cls._current is None:
                raise RuntimeError(
                    "Nenhuma sessão autenticada. "
                    "Chame authenticate(token) primeiro."
                )
            return cls._current

    @classmethod
    def update_context(cls, context: dict[str, Any]) -> None:
        """Atualiza o contexto da sessão de forma imutável (dataclasses.replace)."""
        with cls._lock:
            if cls._current is not None:
                cls._current = dc_replace(cls._current, context=context)

    @classmethod
    def increment_tool_calls(cls) -> int:
        """Incrementa contador de tool calls e retorna o novo total."""
        with cls._lock:
            if cls._current is not None:
                cls._current = dc_replace(
                    cls._current, tool_calls=cls._current.tool_calls + 1
                )
                return cls._current.tool_calls
            return 0


def collect_environment_context(force: bool = False) -> dict[str, Any]:
    """Coleta contexto do ambiente com cache de 60s.

    Remove socket probes (que bloqueavam ~1s); mantém git e OS.
    Seguro para uso concorrente via _context_lock.
    """
    global _context_cache, _context_cached_at

    with _context_lock:
        if (
            not force
            and _context_cache is not None
            and (time.monotonic() - _context_cached_at) < _CONTEXT_TTL
        ):
            return _context_cache

        ctx = _collect_fresh()
        _context_cache = ctx
        _context_cached_at = time.monotonic()
        return ctx


def _collect_fresh() -> dict[str, Any]:
    """Coleta git + OS. Sem socket probes."""
    # ── Git context ───────────────────────────────────────────────────────── #
    git_info: dict[str, Any] = {}
    try:
        branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=3,
        )
        if branch.returncode == 0:
            git_info["branch"] = branch.stdout.strip()

        repo = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=3,
        )
        if repo.returncode == 0:
            git_info["repo"] = os.path.basename(repo.stdout.strip())
            git_info["repo_path"] = repo.stdout.strip()

        sha = subprocess.run(
            ["git", "rev-parse", "--short=7", "HEAD"],
            capture_output=True, text=True, timeout=3,
        )
        if sha.returncode == 0:
            git_info["head_sha"] = sha.stdout.strip()
    except Exception:  # noqa: BLE001
        pass

    # ── OS / runtime ──────────────────────────────────────────────────────── #
    os_info = {
        "system": platform.system(),
        "hostname": platform.node(),
        "python": platform.python_version(),
        "cwd": os.getcwd(),
        "user": os.getenv("USER") or os.getenv("USERNAME", "unknown"),
    }

    return {
        "git": git_info,
        "os": os_info,
        "captured_at": datetime.now(timezone.utc).isoformat(),
    }
