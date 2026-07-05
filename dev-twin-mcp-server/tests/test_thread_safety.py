"""Testes de thread-safety do SessionManager.

Verifica que múltiplas threads concorrendo em set/get/clear não causam
race conditions ou corrupção de estado.
"""
from __future__ import annotations

import threading

import pytest

from src.knowledge.session import SessionManager, UserSession


def _make_session(name: str) -> UserSession:
    return UserSession(
        token="tok",
        user_id=f"uid_{name}",
        name=name,
        email=f"{name.lower()}@test.com",
        role="developer",
        scopes=["*"],
        environment="dev",
        authenticated_at="2024-01-01T00:00:00+00:00",
        context={},
    )


@pytest.fixture(autouse=True)
def clear():
    SessionManager.clear()
    yield
    SessionManager.clear()


class TestSessionManagerThreadSafety:
    def test_concurrent_set_does_not_corrupt(self):
        """N threads fazendo set() concorrentemente — nenhuma deve ver estado None."""
        errors: list[str] = []
        barrier = threading.Barrier(10)

        def worker(name: str):
            barrier.wait()  # sincroniza início
            SessionManager.set(_make_session(name))
            s = SessionManager.get()
            if s is None:
                errors.append(f"{name}: got None after set")

        threads = [threading.Thread(target=worker, args=(f"user{i}",)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Race condition detected: {errors}"

    def test_concurrent_get_and_clear(self):
        """set() + clear() concorrentes não causam exceção."""
        SessionManager.set(_make_session("Alice"))
        exceptions: list[Exception] = []

        def reader():
            for _ in range(50):
                SessionManager.get()
                SessionManager.is_authenticated()

        def clearer():
            for _ in range(10):
                SessionManager.clear()
                SessionManager.set(_make_session("Alice"))

        threads = [threading.Thread(target=reader) for _ in range(4)]
        threads.append(threading.Thread(target=clearer))
        try:
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        except Exception as exc:
            exceptions.append(exc)

        assert not exceptions

    def test_update_context_thread_safe(self):
        """update_context() não corrompe outros campos da sessão."""
        SessionManager.set(_make_session("Bob"))
        errors: list[str] = []

        def updater(i: int):
            SessionManager.update_context({"run": i})
            s = SessionManager.get()
            if s and s.name != "Bob":
                errors.append(f"name corrupted: {s.name}")

        threads = [threading.Thread(target=updater, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        # name preservado após todos os updates
        assert SessionManager.get().name == "Bob"

    def test_require_raises_when_not_authenticated(self):
        """require() levanta RuntimeError quando sem sessão."""
        SessionManager.clear()
        with pytest.raises(RuntimeError, match="authenticate"):
            SessionManager.require()

    def test_require_returns_session_when_authenticated(self):
        """require() retorna sessão válida."""
        SessionManager.set(_make_session("Carol"))
        s = SessionManager.require()
        assert s.name == "Carol"
