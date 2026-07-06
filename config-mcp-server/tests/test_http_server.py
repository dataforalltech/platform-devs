"""Testes do wrapper FastAPI config-mcp (src/server/http_server.py).

O postgres_sync é mockado — nenhuma conexão real é feita.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from src.server.http_server import create_config_http_server


@pytest.fixture()
def pg():
    return MagicMock()


@pytest.fixture()
def client(pg):
    config_store = SimpleNamespace(postgres_sync=pg)
    app = create_config_http_server(config_store, tenant_id="tenant_test")
    return TestClient(app)


class TestHealth:
    def test_health(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["service"] == "config-mcp"
        assert body["tenant_id"] == "tenant_test"


class TestCredentialsRoutes:
    def test_list_success(self, client, pg):
        pg.list_credentials_for_namespace.return_value = [{"namespace": "n", "key": "k"}]
        resp = client.get("/credentials/list")
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    def test_list_error_maps_to_http_exception(self, client, pg):
        pg.list_credentials_for_namespace.return_value = None  # → status 500
        resp = client.get("/credentials/list")
        assert resp.status_code == 500

    def test_metadata_success(self, client, pg):
        pg.get_credential_metadata.return_value = {"namespace": "n", "key": "k", "active": True}
        resp = client.get("/credentials/metadata", params={"namespace": "n", "key": "k"})
        assert resp.status_code == 200

    def test_metadata_not_found(self, client, pg):
        pg.get_credential_metadata.return_value = None
        resp = client.get("/credentials/metadata", params={"namespace": "n", "key": "k"})
        assert resp.status_code == 404

    def test_validate_success(self, client, pg):
        pg.get_credential_metadata.return_value = {"active": True, "expires_at": None}
        resp = client.post("/credentials/validate", params={"namespace": "n", "key": "k"})
        assert resp.status_code == 200
        assert resp.json()["valid"] is True

    def test_validate_not_found(self, client, pg):
        pg.get_credential_metadata.return_value = None
        resp = client.post("/credentials/validate", params={"namespace": "n", "key": "k"})
        assert resp.status_code == 404

    def test_rotate_success(self, client, pg):
        resp = client.post(
            "/credentials/rotate",
            params={"namespace": "n", "key": "k", "new_value": "v"},
        )
        assert resp.status_code == 200
        assert resp.json()["rotated"] is True

    def test_delete_success(self, client, pg):
        pg.get_credential_metadata.return_value = {"active": True}
        resp = client.delete("/credentials", params={"namespace": "n", "key": "k"})
        assert resp.status_code == 200
        assert resp.json()["deleted"] is True

    def test_delete_not_found(self, client, pg):
        pg.get_credential_metadata.return_value = None
        resp = client.delete("/credentials", params={"namespace": "n", "key": "k"})
        assert resp.status_code == 404

    def test_namespaces_success(self, client, pg):
        pg.list_credential_namespaces.return_value = ["credentials.github"]
        resp = client.get("/credentials/namespaces")
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    def test_namespaces_error(self, client, pg):
        pg.list_credential_namespaces.side_effect = RuntimeError("boom")
        resp = client.get("/credentials/namespaces")
        assert resp.status_code == 500
