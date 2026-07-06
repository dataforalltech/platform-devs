"""Testes da HTTP API interna (src/api/router.py) via FastAPI TestClient."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.router import make_router


@pytest.fixture()
def api_token() -> str:
    return "test-token-123"


def _client(store, token: str) -> TestClient:
    app = FastAPI()
    app.include_router(make_router(store, token))
    return TestClient(app, raise_server_exceptions=True)


@pytest.fixture()
def auth_headers(api_token) -> dict:
    return {"Authorization": f"Bearer {api_token}"}


class TestHealth:
    def test_health_open(self, store, api_token):
        client = _client(store, api_token)
        resp = client.get("/v1/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


class TestAuth:
    def test_missing_token_401(self, store, api_token):
        client = _client(store, api_token)
        resp = client.get("/v1/namespaces")
        assert resp.status_code == 401

    def test_wrong_token_401(self, store, api_token):
        client = _client(store, api_token)
        resp = client.get("/v1/namespaces", headers={"Authorization": "Bearer nope"})
        assert resp.status_code == 401

    def test_correct_token_200(self, store, api_token, auth_headers):
        client = _client(store, api_token)
        resp = client.get("/v1/namespaces", headers=auth_headers)
        assert resp.status_code == 200

    def test_auth_disabled_when_token_empty(self, store):
        client = _client(store, "")
        resp = client.get("/v1/namespaces")
        assert resp.status_code == 200


class TestNamespacesAndCredentials:
    def test_list_namespaces(self, store, api_token, auth_headers):
        store.set("credentials.acr", "ACR_USER", "u")
        client = _client(store, api_token)
        resp = client.get("/v1/namespaces", headers=auth_headers)
        assert "credentials.acr" in resp.json()["namespaces"]

    def test_get_credential_found(self, store, api_token, auth_headers):
        store.set("credentials.acr", "ACR_USER", "u")
        client = _client(store, api_token)
        resp = client.get("/v1/credentials/credentials.acr/ACR_USER", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["value"] == "u"

    def test_get_credential_not_found_404(self, store, api_token, auth_headers):
        client = _client(store, api_token)
        resp = client.get("/v1/credentials/credentials.acr/MISSING", headers=auth_headers)
        assert resp.status_code == 404

    def test_list_namespace_keys(self, store, api_token, auth_headers):
        store.set("credentials.acr", "ACR_USER", "u")
        store.set("credentials.acr", "ACR_PASSWORD", "p")
        client = _client(store, api_token)
        resp = client.get("/v1/credentials/credentials.acr", headers=auth_headers)
        assert sorted(resp.json()["keys"]) == ["ACR_PASSWORD", "ACR_USER"]


class TestEnvAndTenants:
    def test_get_env_config(self, store, api_token, auth_headers):
        store.set("env.dev", "DATABASE_URL", "postgres://x")
        client = _client(store, api_token)
        resp = client.get("/v1/env/dev", headers=auth_headers)
        assert resp.json()["DATABASE_URL"] == "postgres://x"

    def test_list_tenants(self, store, api_token, auth_headers):
        store.set("tenants.t1", "K", "V")
        store.set("tenants.t2", "K", "V")
        client = _client(store, api_token)
        resp = client.get("/v1/tenants", headers=auth_headers)
        assert resp.json()["tenants"] == ["t1", "t2"]

    def test_get_tenant_config_found(self, store, api_token, auth_headers):
        store.set("tenants.t1", "DATABASE_URL", "postgres://x")
        client = _client(store, api_token)
        resp = client.get("/v1/tenants/t1", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["DATABASE_URL"] == "postgres://x"

    def test_get_tenant_config_not_found_404(self, store, api_token, auth_headers):
        client = _client(store, api_token)
        resp = client.get("/v1/tenants/unknown", headers=auth_headers)
        assert resp.status_code == 404


class TestPhysical:
    def test_physical_endpoint(self, store, api_token, auth_headers, monkeypatch):
        monkeypatch.setattr(
            "src.api.router.collect_physical_info",
            lambda: {"os": {"system": "TestOS"}, "cpu": {}, "ram": {}, "disks": [], "network": {}},
        )
        client = _client(store, api_token)
        resp = client.get("/v1/physical", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["os"]["system"] == "TestOS"
