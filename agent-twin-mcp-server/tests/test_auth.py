"""Testes das auth tools."""
from __future__ import annotations

import pytest

from src.knowledge.token_store import TokenStore
from src.knowledge.session import SessionManager
from src.tools.auth_tool import authenticate, whoami, get_twin_context, refresh_context
from src.tools.admin_tool import register_token, revoke_token, list_tokens, rotate_token


@pytest.fixture(autouse=True)
def clear_session():
    """Garante sessão limpa entre testes."""
    SessionManager.clear()
    yield
    SessionManager.clear()


class TestAuthenticate:
    def test_valid_token(self, store):
        record = store.register(name="Alice", email="alice@test.com")
        result = authenticate(store, record["token"])
        assert result["authenticated"] is True
        assert result["name"] == "Alice"
        # authenticate() é slim — sem contexto (coletado lazy em get_twin_context)
        assert "context" not in result

    def test_invalid_token(self, store):
        result = authenticate(store, "bad-token")
        assert result["authenticated"] is False
        assert "error" in result

    def test_sets_session(self, store):
        record = store.register(name="Bob", email="bob@test.com")
        authenticate(store, record["token"])
        assert SessionManager.is_authenticated()
        assert SessionManager.get().name == "Bob"

    def test_revoked_token_fails(self, store):
        record = store.register(name="Carol", email="carol@test.com")
        store.revoke(record["token"])
        result = authenticate(store, record["token"])
        assert result["authenticated"] is False


class TestWhoami:
    def test_no_session(self):
        result = whoami()
        assert result["authenticated"] is False

    def test_after_authenticate(self, store):
        record = store.register(name="Dave", email="dave@test.com")
        authenticate(store, record["token"])
        result = whoami()
        assert result["authenticated"] is True
        assert result["name"] == "Dave"
        assert result["email"] == "dave@test.com"


class TestGetTwinContext:
    def test_no_session(self):
        result = get_twin_context()
        assert result["authenticated"] is False

    def test_with_session(self, store):
        record = store.register(name="Eve", email="eve@test.com", environment="staging")
        authenticate(store, record["token"])
        result = get_twin_context()
        assert result["authenticated"] is True
        assert result["user"]["environment"] == "staging"
        assert "context" in result
        assert "credential_namespaces" in result

    def test_tenant_id_in_context(self, store):
        record = store.register(name="Frank", email="frank@test.com", tenant_id="tenant_abc")
        authenticate(store, record["token"])
        result = get_twin_context()
        assert result["user"]["tenant_id"] == "tenant_abc"
        assert "tenants.tenant_abc" in result["tenant_namespaces"]

    def test_no_tenant_gives_empty_namespaces(self, store):
        record = store.register(name="Grace", email="grace@test.com")
        authenticate(store, record["token"])
        result = get_twin_context()
        assert result["user"]["tenant_id"] is None
        assert result["tenant_namespaces"] == []


class TestAdminTools:
    def test_register_requires_admin_token(self, store, admin_token):
        result = register_token(
            store, admin_token_configured=admin_token,
            admin_token="wrong", name="X", email="x@test.com",
        )
        assert "error" in result
        assert result["error"] == "Unauthorized"

    def test_register_success(self, store, admin_token):
        result = register_token(
            store, admin_token_configured=admin_token,
            admin_token=admin_token, name="Frank", email="frank@test.com",
        )
        assert result["success"] is True
        assert result["token"]
        assert result["warning"]

    def test_list_tokens(self, store, admin_token):
        store.register(name="G", email="g@test.com")
        result = list_tokens(store, admin_token_configured=admin_token, admin_token=admin_token)
        assert result["count"] >= 1
        for t in result["tokens"]:
            assert "token" not in t

    def test_revoke_via_admin(self, store, admin_token):
        record = store.register(name="H", email="h@test.com")
        result = revoke_token(
            store, admin_token_configured=admin_token,
            admin_token=admin_token, identifier=record["token"],
        )
        assert result["success"] is True

    def test_rotate_via_admin(self, store, admin_token):
        record = store.register(name="I", email="i@test.com")
        result = rotate_token(
            store, admin_token_configured=admin_token,
            admin_token=admin_token, identifier=record["user_id"],
        )
        assert result["success"] is True
        assert result["new_token"] != record["token"]

    def test_register_with_tenant_id(self, store, admin_token):
        result = register_token(
            store, admin_token_configured=admin_token,
            admin_token=admin_token, name="J", email="j@test.com",
            tenant_id="tenant_xyz99",
        )
        assert result["success"] is True
        assert result["tenant_id"] == "tenant_xyz99"
        # Verificar que a sessão carrega o tenant_id ao autenticar (resposta slim)
        auth = authenticate(store, result["token"])
        assert auth["tenant_id"] == "tenant_xyz99"
