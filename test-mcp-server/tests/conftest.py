"""Fixtures compartilhadas para os testes do test-mcp-server."""

import pytest

from src.db.store import TestStore


@pytest.fixture
def store(tmp_path) -> TestStore:
    """TestStore em banco temporário."""
    return TestStore(str(tmp_path / "test.db"))


@pytest.fixture
def plan(store: TestStore) -> dict:
    """Plano de teste pré-criado."""
    return store.create_plan(title="Plano de Teste", scope="Endpoint GET /api/items", feature="items-list")
