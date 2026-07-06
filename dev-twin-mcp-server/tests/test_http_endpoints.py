"""Testes dos DevTwinHTTPEndpoints (sync PostgreSQL mockado)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.server.http_endpoints import DevTwinHTTPEndpoints


@pytest.fixture()
def sync():
    m = MagicMock()
    m.sync_user_login.return_value = None
    m.log_action.return_value = None
    m.revoke_token.return_value = {"revoked": True}
    return m


@pytest.fixture()
def endpoints(sync):
    return DevTwinHTTPEndpoints(postgres_sync=sync)


class TestLogin:
    def test_login_success(self, endpoints, sync):
        resp = endpoints.post_auth_login("admin@example.com", "password_admin")
        assert resp["status"] == 200
        assert resp["token"].startswith("twn_")
        assert resp["session_token"].startswith("sess_")
        assert resp["user"]["email"] == "admin@example.com"
        assert resp["user"]["role"] == "admin"
        sync.sync_user_login.assert_called_once()
        sync.log_action.assert_called()

    def test_login_invalid_credentials(self, endpoints):
        resp = endpoints.post_auth_login("admin@example.com", "wrong")
        assert resp["status"] == 401
        assert resp["error"] == "invalid_credentials"

    def test_login_unknown_user(self, endpoints):
        resp = endpoints.post_auth_login("nobody@example.com", "whatever")
        assert resp["status"] == 401

    def test_login_missing_fields(self, endpoints):
        resp = endpoints.post_auth_login("", "")
        assert resp["status"] == 401

    def test_login_internal_error(self, endpoints, sync):
        sync.sync_user_login.side_effect = RuntimeError("db down")
        resp = endpoints.post_auth_login("dev@example.com", "password_developer")
        assert resp["status"] == 500
        assert resp["error"] == "internal_error"


class TestValidate:
    def test_validate_long_lived_token(self, endpoints):
        token = "twn_" + "a" * 80
        resp = endpoints.get_auth_validate(token)
        assert resp["status"] == 200
        assert resp["valid"] is True
        assert resp["user"]["token_type"] if "token_type" in resp["user"] else True

    def test_validate_session_token(self, endpoints):
        token = "sess_" + "b" * 80
        resp = endpoints.get_auth_validate(token)
        assert resp["status"] == 200
        assert resp["valid"] is True

    def test_validate_invalid_token(self, endpoints):
        resp = endpoints.get_auth_validate("garbage")
        assert resp["status"] == 401
        assert resp["valid"] is False

    def test_validate_empty_token(self, endpoints):
        resp = endpoints.get_auth_validate("")
        assert resp["status"] == 401


class TestLogout:
    def test_logout_success(self, endpoints, sync):
        resp = endpoints.post_auth_logout("dev@example.com", "twn_" + "c" * 80)
        assert resp["status"] == 200
        assert resp["status_message"] == "logged_out"
        sync.log_action.assert_called()

    def test_logout_internal_error(self, endpoints, sync):
        sync.log_action.side_effect = RuntimeError("boom")
        resp = endpoints.post_auth_logout("dev@example.com", "twn_x")
        assert resp["status"] == 500


class TestUsers:
    def test_get_users_success(self, endpoints, sync):
        sync.list_users.return_value = [
            {"id": 1, "email": "a@x.com", "role": "developer"},
            {"id": 2, "email": "b@x.com", "role": "admin"},
        ]
        resp = endpoints.get_users()
        assert resp["status"] == 200
        assert resp["total"] == 2

    def test_get_users_db_error(self, endpoints, sync):
        sync.list_users.return_value = None
        resp = endpoints.get_users()
        assert resp["status"] == 500
        assert resp["error"] == "database_error"

    def test_get_users_internal_error(self, endpoints, sync):
        sync.list_users.side_effect = RuntimeError("boom")
        resp = endpoints.get_users(role="admin")
        assert resp["status"] == 500
        assert resp["error"] == "internal_error"


class TestRevokeHelper:
    def test_revoke_delegates_to_sync(self, endpoints, sync):
        assert endpoints._revoke_token("twn_x") is True
        sync.revoke_token.assert_called_once_with("twn_x")

    def test_revoke_handles_failure(self, endpoints, sync):
        sync.revoke_token.side_effect = RuntimeError("boom")
        assert endpoints._revoke_token("twn_x") is False


class TestTokenGeneration:
    def test_tokens_are_unique(self, endpoints):
        user = {"id": 1, "email": "x@x.com"}
        assert endpoints._generate_token(user) != endpoints._generate_token(user)
        assert endpoints._generate_session_token(user) != endpoints._generate_session_token(user)
