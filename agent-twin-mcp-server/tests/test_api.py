"""Testes da HTTP API do agent-twin-mcp (:7098).

Cobre:
- /v1/health: sem campo `authenticated` (evitar info leak)
- /v1/session/check-scope: 403 quando escopo negado
- /v1/session/scopes: removido (deve retornar 404/405)
- Autenticação Bearer com secrets.compare_digest
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api.router import make_router
from src.knowledge.session import SessionManager, UserSession


@pytest.fixture(autouse=True)
def clear_session():
    SessionManager.clear()
    yield
    SessionManager.clear()


@pytest.fixture
def api_token() -> str:
    return "test-api-token-123"


@pytest.fixture
def client(api_token: str):
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(make_router(api_token))
    return TestClient(app, raise_server_exceptions=True)


@pytest.fixture
def auth_headers(api_token: str) -> dict:
    return {"Authorization": f"Bearer {api_token}"}


def _set_session(name="Alice", scopes=None, role="developer"):
    SessionManager.set(UserSession(
        token="tok",
        user_id="uid_alice",
        name=name,
        email=f"{name.lower()}@test.com",
        role=role,
        scopes=scopes or ["deploy", "qa"],
        environment="dev",
        authenticated_at="2024-01-01T00:00:00+00:00",
        context={"git": {"branch": "main"}},
    ))


class TestHealth:
    def test_health_ok(self, client):
        resp = client.get("/v1/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"

    def test_health_has_no_authenticated_field(self, client):
        """Campo 'authenticated' NÃO deve aparecer no health endpoint."""
        resp = client.get("/v1/health")
        assert "authenticated" not in resp.json()


class TestBearerAuth:
    def test_wrong_token_returns_401(self, client):
        resp = client.get(
            "/v1/session",
            headers={"Authorization": "Bearer wrong-token"},
        )
        assert resp.status_code == 401

    def test_no_token_returns_401(self, client):
        resp = client.get("/v1/session")
        assert resp.status_code == 401

    def test_correct_token_passes(self, client, auth_headers):
        _set_session()
        resp = client.get("/v1/session", headers=auth_headers)
        assert resp.status_code == 200


class TestCheckScope:
    def test_allowed_scope_returns_200(self, client, auth_headers):
        _set_session(scopes=["deploy", "qa"])
        resp = client.post(
            "/v1/session/check-scope",
            json={"scope": "deploy"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["allowed"] is True

    def test_denied_scope_returns_403(self, client, auth_headers):
        """check-scope deve retornar 403 (não 200) quando escopo negado."""
        _set_session(scopes=["qa"])
        resp = client.post(
            "/v1/session/check-scope",
            json={"scope": "deploy"},
            headers=auth_headers,
        )
        assert resp.status_code == 403

    def test_wildcard_scope_allows_all(self, client, auth_headers):
        _set_session(scopes=["*"])
        resp = client.post(
            "/v1/session/check-scope",
            json={"scope": "anything"},
            headers=auth_headers,
        )
        assert resp.status_code == 200


class TestScopesEndpointRemoved:
    def test_scopes_endpoint_not_found(self, client, auth_headers):
        """/v1/session/scopes foi removido — deve retornar 404 ou 405."""
        resp = client.get("/v1/session/scopes", headers=auth_headers)
        assert resp.status_code in (404, 405)


class TestSessionEndpoints:
    def test_session_user_includes_tenant_id(self, client, auth_headers):
        _set_session()
        resp = client.get("/v1/session/user", headers=auth_headers)
        assert resp.status_code == 200
        assert "tenant_id" in resp.json()

    def test_tenant_endpoint_no_session(self, client, auth_headers):
        resp = client.get("/v1/session/tenant", headers=auth_headers)
        assert resp.status_code == 404
