"""Fixtures para testes do agent-twin-mcp-server."""
from __future__ import annotations

import pytest

from src.knowledge.token_store import TokenStore


@pytest.fixture()
def store(tmp_path) -> TokenStore:
    return TokenStore(str(tmp_path / "test_twin.db"))


@pytest.fixture()
def admin_token() -> str:
    return "admin-secret-token-for-tests"
