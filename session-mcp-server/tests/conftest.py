"""Fixtures compartilhadas para testes do session-mcp-server.

O ``SessionStore`` é SQLite embarcado (hermético): nenhuma conexão de rede/DB é
aberta, então os testes rodam sem PostgreSQL nem o gateway.
"""

from __future__ import annotations

import pytest

from src.config.settings import SessionSettings
from src.db.store import SessionStore
from src.tools.session_tool import start_session


@pytest.fixture
def store() -> SessionStore:
    """SessionStore hermético (SQLite in-memory) — isolado por teste."""
    s = SessionStore(SessionSettings())
    yield s
    s.close()


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
