"""Fixtures compartilhadas para testes do session-mcp-server."""

from __future__ import annotations

import pytest

from src.db.store import SessionStore
from src.tools.session_tool import start_session


@pytest.fixture
def store(tmp_path) -> SessionStore:
    """SessionStore em banco temporário — isolado por teste."""
    return SessionStore(db_path=str(tmp_path / "test_sessions.db"))


@pytest.fixture
def active_session(store: SessionStore) -> dict:
    """Cria e retorna uma sessão ativa via start_session (com branch sugerida)."""
    return start_session(
        store,
        "develop",
        title="Test Session",
        objective="Testar o session-mcp-server",
        repo="platform-service-template",
    )
