"""Testes de ConfigHTTPEndpoints com postgres_sync mockado (hermetico, sem DB real)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.server.http_endpoints import ConfigHTTPEndpoints


@pytest.fixture()
def pg():
    return MagicMock()


@pytest.fixture()
def endpoints(pg):
    return ConfigHTTPEndpoints(pg, tenant_id="tenant_test")


class TestCredentialsList:
    def test_success(self, endpoints, pg):
        pg.list_credentials_for_namespace.return_value = [
            {"namespace": "credentials.github", "key": "GITHUB_TOKEN", "active": True}
        ]
        result = endpoints.get_credentials_list(namespace="credentials.github")
        assert result["status"] == 200
        assert result["total"] == 1
        assert result["tenant_id"] == "tenant_test"

    def test_default_namespace_filter(self, endpoints, pg):
        pg.list_credentials_for_namespace.return_value = []
        endpoints.get_credentials_list()
        pg.list_credentials_for_namespace.assert_called_once_with(namespace="credentials.*")

    def test_database_error(self, endpoints, pg):
        pg.list_credentials_for_namespace.return_value = None
        result = endpoints.get_credentials_list()
        assert result["status"] == 500
        assert result["error"] == "database_error"

    def test_exception(self, endpoints, pg):
        pg.list_credentials_for_namespace.side_effect = RuntimeError("boom")
        result = endpoints.get_credentials_list()
        assert result["status"] == 500
        assert result["error"] == "internal_error"


class TestCredentialsMetadata:
    def test_found(self, endpoints, pg):
        pg.get_credential_metadata.return_value = {"namespace": "n", "key": "k", "active": True}
        result = endpoints.get_credentials_metadata("n", "k")
        assert result["status"] == 200
        assert result["active"] is True

    def test_not_found(self, endpoints, pg):
        pg.get_credential_metadata.return_value = None
        result = endpoints.get_credentials_metadata("n", "k")
        assert result["status"] == 404

    def test_exception(self, endpoints, pg):
        pg.get_credential_metadata.side_effect = RuntimeError("boom")
        result = endpoints.get_credentials_metadata("n", "k")
        assert result["status"] == 500


class TestCredentialsValidate:
    def test_active_not_expired(self, endpoints, pg):
        pg.get_credential_metadata.return_value = {"active": True, "expires_at": None}
        result = endpoints.post_credentials_validate("n", "k")
        assert result["status"] == 200
        assert result["valid"] is True
        assert result["is_expired"] is False

    def test_expired(self, endpoints, pg):
        pg.get_credential_metadata.return_value = {
            "active": True,
            "expires_at": "2000-01-01T00:00:00Z",
        }
        result = endpoints.post_credentials_validate("n", "k")
        assert result["is_expired"] is True
        assert result["valid"] is False

    def test_not_found(self, endpoints, pg):
        pg.get_credential_metadata.return_value = None
        result = endpoints.post_credentials_validate("n", "k")
        assert result["status"] == 404
        assert result["valid"] is False

    def test_exception(self, endpoints, pg):
        pg.get_credential_metadata.side_effect = RuntimeError("boom")
        result = endpoints.post_credentials_validate("n", "k")
        assert result["status"] == 500


class TestCredentialsRotate:
    def test_success(self, endpoints, pg):
        result = endpoints.post_credentials_rotate("n", "k", "newval")
        assert result["status"] == 200
        assert result["rotated"] is True
        pg.update_credential.assert_called_once_with("n", "k", "newval")
        pg.sync_credential_expires.assert_called_once()
        pg.log_action.assert_called_once()

    def test_exception(self, endpoints, pg):
        pg.sync_credential_expires.side_effect = RuntimeError("boom")
        result = endpoints.post_credentials_rotate("n", "k", "v")
        assert result["status"] == 500


class TestCredentialsDelete:
    def test_success(self, endpoints, pg):
        pg.get_credential_metadata.return_value = {"active": True}
        result = endpoints.delete_credentials("n", "k")
        assert result["status"] == 200
        assert result["deleted"] is True
        pg.sync_credential_deleted.assert_called_once_with("n", "k")

    def test_not_found(self, endpoints, pg):
        pg.get_credential_metadata.return_value = None
        result = endpoints.delete_credentials("n", "k")
        assert result["status"] == 404

    def test_exception(self, endpoints, pg):
        pg.get_credential_metadata.side_effect = RuntimeError("boom")
        result = endpoints.delete_credentials("n", "k")
        assert result["status"] == 500


class TestNamespaces:
    def test_success(self, endpoints, pg):
        pg.list_credential_namespaces.return_value = ["credentials.github", "env.dev"]
        result = endpoints.get_credentials_namespaces()
        assert result["status"] == 200
        assert result["total"] == 2

    def test_exception(self, endpoints, pg):
        pg.list_credential_namespaces.side_effect = RuntimeError("boom")
        result = endpoints.get_credentials_namespaces()
        assert result["status"] == 500


class TestUpdateHelper:
    def test_update_value_true(self, endpoints, pg):
        assert endpoints._update_credential_value("n", "k", "v") is True
        pg.update_credential.assert_called_once_with("n", "k", "v")

    def test_update_value_handles_exception(self, endpoints, pg):
        pg.update_credential.side_effect = RuntimeError("boom")
        assert endpoints._update_credential_value("n", "k", "v") is False

    def test_update_value_no_postgres(self):
        ep = ConfigHTTPEndpoints(None, "t")
        assert ep._update_credential_value("n", "k", "v") is True
