"""Testes do FastAPI wrapper (http_server.create_services_http_server).

Herméticos: usa TestClient em memória; postgres_sync é um MagicMock — sem I/O real.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from src.server.http_server import create_services_http_server


@pytest.fixture
def client_and_sync():
    sync = MagicMock()
    registry = MagicMock()
    registry.postgres_sync = sync
    app = create_services_http_server(registry)
    with TestClient(app) as client:
        yield client, sync


def test_health(client_and_sync):
    client, _ = client_and_sync
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["service"] == "services-mcp"


def test_get_services_ok(client_and_sync):
    client, sync = client_and_sync
    sync.list_services.return_value = [{"name": "a", "type": "docker"}]
    r = client.get("/services")
    assert r.status_code == 200
    assert r.json()["total"] == 1


def test_get_services_error_raises_http(client_and_sync):
    client, sync = client_and_sync
    sync.list_services.return_value = None
    r = client.get("/services")
    assert r.status_code == 500


def test_get_service_found(client_and_sync):
    client, sync = client_and_sync
    sync.get_service.return_value = {"name": "svcx", "port": 1}
    r = client.get("/services/svcx")
    assert r.status_code == 200
    assert r.json()["name"] == "svcx"


def test_get_service_not_found(client_and_sync):
    client, sync = client_and_sync
    sync.get_service.return_value = None
    r = client.get("/services/ghost")
    assert r.status_code == 404


def test_post_service_created(client_and_sync):
    client, sync = client_and_sync
    sync.get_service.return_value = None
    r = client.post(
        "/services",
        params={"name": "new", "service_type": "docker", "host": "h", "port": 1},
    )
    # HTTP 200 (FastAPI default); o envelope carrega status=201 e o nome do serviço.
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == 201
    assert body["name"] == "new"


def test_post_service_conflict(client_and_sync):
    client, sync = client_and_sync
    sync.get_service.return_value = {"name": "new"}
    r = client.post(
        "/services",
        params={"name": "new", "service_type": "docker", "host": "h", "port": 1},
    )
    assert r.status_code == 409


def test_patch_service_ok(client_and_sync):
    client, sync = client_and_sync
    sync.get_service.return_value = {"name": "svcx"}
    r = client.patch("/services/svcx", params={"description": "d"})
    assert r.status_code == 200
    assert r.json()["updated"] is True


def test_patch_service_not_found(client_and_sync):
    client, sync = client_and_sync
    sync.get_service.return_value = None
    r = client.patch("/services/ghost", params={"description": "d"})
    assert r.status_code == 404


def test_health_check_endpoint(client_and_sync):
    client, sync = client_and_sync
    sync.get_service.return_value = {"name": "svcx"}
    r = client.post("/services/svcx/health-check", params={"status": "healthy"})
    assert r.status_code == 200
    assert r.json()["service_status"] == "healthy"


def test_delete_service_ok(client_and_sync):
    client, sync = client_and_sync
    sync.get_service.return_value = {"name": "svcx"}
    r = client.delete("/services/svcx")
    assert r.status_code == 200
    assert r.json()["deleted"] is True


def test_delete_service_not_found(client_and_sync):
    client, sync = client_and_sync
    sync.get_service.return_value = None
    r = client.delete("/services/ghost")
    assert r.status_code == 404
