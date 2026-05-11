"""Fixtures compartilhadas para testes do session-mcp-server."""

from __future__ import annotations

import os
import pytest

from src.config.settings import SessionSettings
from src.db.store import SessionStore
from src.tools.session_tool import start_session


@pytest.fixture
def store() -> SessionStore:
    """SessionStore com PostgreSQL de teste — isolado por teste."""
    settings = SessionSettings(
        pg_host=os.getenv("TEST_POSTGRES_HOST", "claude-dev"),
        pg_port=int(os.getenv("TEST_POSTGRES_PORT", "5432")),
        pg_db=os.getenv("TEST_POSTGRES_DB", "app_test"),
        pg_user=os.getenv("TEST_POSTGRES_USER", "postgres"),
        pg_password=os.getenv("TEST_POSTGRES_PASSWORD", "postgres_password_local_dev"),
    )
    s = SessionStore(settings)
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
