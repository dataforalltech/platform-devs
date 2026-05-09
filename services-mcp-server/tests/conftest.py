"""Fixtures compartilhadas para todos os testes do services-mcp-server."""

from __future__ import annotations

import pytest

from src.config.settings import ServicesSettings
from src.db.store import ServiceStore


@pytest.fixture
def store():
    s = ServiceStore(db_path=":memory:")
    yield s
    s.close()


@pytest.fixture
def settings():
    return ServicesSettings(db_path=":memory:", health_timeout=2.0, docker_timeout=5)


def make_service(
    store: ServiceStore,
    name: str = "api-gateway",
    port: int = 8080,
    environment: str = "local",
    type_: str = "docker",
    status: str = "running",
    tags: list[str] | None = None,
) -> None:
    """Helper para registrar serviço nos testes."""
    from src.tools.registry_tool import register_service

    register_service(
        store,
        name=name,
        host="localhost",
        port=port,
        url=f"http://localhost:{port}",
        type=type_,
        environment=environment,
        health_path="/health",
        tags=tags or [],
        metadata={},
        status=status,
    )
