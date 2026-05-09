"""Testes do ConfigStore."""
from __future__ import annotations

import pytest

from src.knowledge.store import ConfigStore, StoreError
from src.tools.credential_tool import (
    delete_credential,
    get_credential,
    list_credentials,
    set_credential,
    set_credential_secure,
)
from src.tools.env_tool import get_env_config, list_environments, set_env_var, sync_env_file
from src.tools.tenant_tool import (
    get_session_tenant_config,
    get_tenant_config,
    list_tenants,
    set_tenant_config,
)


class TestConfigStore:
    def test_set_and_get(self, store):
        store.set("credentials.acr", "ACR_USERNAME", "myuser")
        assert store.get("credentials.acr", "ACR_USERNAME") == "myuser"

    def test_get_missing_returns_none(self, store):
        assert store.get("credentials.acr", "MISSING") is None

    def test_delete_existing(self, store):
        store.set("ns", "key", "val")
        assert store.delete("ns", "key") is True
        assert store.get("ns", "key") is None

    def test_delete_missing_returns_false(self, store):
        assert store.delete("ns", "missing") is False

    def test_list_keys(self, store):
        store.set("credentials.acr", "ACR_USERNAME", "u")
        store.set("credentials.acr", "ACR_PASSWORD", "p")
        keys = store.list_keys("credentials.acr")
        assert sorted(keys["credentials.acr"]) == ["ACR_PASSWORD", "ACR_USERNAME"]

    def test_get_namespace(self, store):
        store.set("env.dev", "DATABASE_URL", "postgres://localhost/db")
        store.set("env.dev", "REDIS_URL", "redis://localhost:6379")
        ns = store.get_namespace("env.dev")
        assert ns["DATABASE_URL"] == "postgres://localhost/db"
        assert ns["REDIS_URL"] == "redis://localhost:6379"

    def test_persistence(self, tmp_path, encryptor):
        path = str(tmp_path / "persist.enc.json")
        s1 = ConfigStore(path, encryptor)
        s1.set("credentials.github", "GITHUB_TOKEN", "ghp_secret")

        s2 = ConfigStore(path, encryptor)
        assert s2.get("credentials.github", "GITHUB_TOKEN") == "ghp_secret"

    def test_namespace_deleted_when_empty(self, store):
        store.set("ns", "key", "val")
        store.delete("ns", "key")
        assert "ns" not in store.list_namespaces()


class TestCredentialTools:
    def test_set_and_get(self, store):
        set_credential(store, "credentials.acr", "ACR_USERNAME", "user123")
        result = get_credential(store, "credentials.acr", "ACR_USERNAME")
        assert result["found"] is True
        assert result["value"] == "user123"

    def test_get_missing(self, store):
        result = get_credential(store, "credentials.acr", "MISSING")
        assert result["found"] is False

    def test_list(self, store):
        set_credential(store, "credentials.acr", "ACR_USERNAME", "u")
        result = list_credentials(store, "credentials.acr")
        assert "ACR_USERNAME" in result["namespaces"]["credentials.acr"]

    def test_delete(self, store):
        set_credential(store, "credentials.acr", "ACR_PASSWORD", "secret")
        result = delete_credential(store, "credentials.acr", "ACR_PASSWORD")
        assert result["deleted"] is True

    def test_set_credential_secure_via_mock(self, store, monkeypatch):
        """set_credential_secure nunca recebe o valor pelo canal MCP — usa getpass."""
        import getpass
        monkeypatch.setattr(getpass, "getpass", lambda prompt="": "super_secret_password")
        result = set_credential_secure(store, "credentials.e2e", "E2E_USER_PASSWORD")
        assert result["success"] is True
        # Valor deve estar armazenado corretamente
        assert store.get("credentials.e2e", "E2E_USER_PASSWORD") == "super_secret_password"
        # Valor NÃO aparece no resultado da tool
        assert "super_secret_password" not in str(result)

    def test_set_credential_secure_empty_value(self, store, monkeypatch):
        """Valor vazio não deve ser armazenado."""
        import getpass
        monkeypatch.setattr(getpass, "getpass", lambda prompt="": "")
        result = set_credential_secure(store, "credentials.e2e", "E2E_USER_PASSWORD")
        assert result["success"] is False
        assert store.get("credentials.e2e", "E2E_USER_PASSWORD") is None


class TestEnvTools:
    def test_set_and_get(self, store):
        set_env_var(store, "dev", "DATABASE_URL", "postgres://localhost/db")
        result = get_env_config(store, "dev")
        assert result["config"]["DATABASE_URL"] == "postgres://localhost/db"

    def test_list_environments(self, store):
        set_env_var(store, "dev", "A", "1")
        set_env_var(store, "production", "B", "2")
        result = list_environments(store)
        assert "dev" in result["environments"]
        assert "production" in result["environments"]

    def test_sync_env_file(self, store, tmp_path):
        set_env_var(store, "dev", "DATABASE_URL", "postgres://localhost/db")
        set_env_var(store, "dev", "REDIS_URL", "redis://localhost")
        path = str(tmp_path / ".env.dev")
        result = sync_env_file(store, path, "dev")
        assert result["success"] is True
        content = open(path).read()
        assert "DATABASE_URL=postgres://localhost/db" in content
        assert "REDIS_URL=redis://localhost" in content


class TestTenantTools:
    def test_set_and_get(self, store):
        set_tenant_config(store, "tenant_abc", "DATABASE_URL", "postgres://localhost/abc")
        result = get_tenant_config(store, "tenant_abc")
        assert result["found"] is True
        assert result["config"]["DATABASE_URL"] == "postgres://localhost/abc"

    def test_list_tenants(self, store):
        set_tenant_config(store, "tenant_a", "K", "V")
        set_tenant_config(store, "tenant_b", "K", "V")
        result = list_tenants(store)
        assert "tenant_a" in result["tenants"]
        assert "tenant_b" in result["tenants"]


class TestSessionTenantTool:
    def test_no_twin_returns_error(self, store, monkeypatch):
        """Sem agent-twin disponível, retorna erro descritivo."""
        import src.tools.tenant_tool as tt
        monkeypatch.setattr(tt, "_get_twin_tenant_id", lambda: None)
        result = get_session_tenant_config(store)
        assert result["found"] is False
        assert result["error"] == "no_tenant_in_session"
        assert "hint" in result

    def test_resolves_tenant_from_twin(self, store, monkeypatch):
        """Com twin disponível, retorna config do tenant da sessão."""
        import src.tools.tenant_tool as tt
        set_tenant_config(store, "tenant_session_01", "DB_URL", "postgres://session/db")
        monkeypatch.setattr(tt, "_get_twin_tenant_id", lambda: "tenant_session_01")
        result = get_session_tenant_config(store)
        assert result["found"] is True
        assert result["tenant_id"] == "tenant_session_01"
        assert result["config"]["DB_URL"] == "postgres://session/db"

    def test_twin_tenant_not_configured_in_store(self, store, monkeypatch):
        """Twin retorna tenant_id mas não há config no store."""
        import src.tools.tenant_tool as tt
        monkeypatch.setattr(tt, "_get_twin_tenant_id", lambda: "tenant_nonexistent")
        result = get_session_tenant_config(store)
        assert result["found"] is False
        assert result["tenant_id"] == "tenant_nonexistent"
        # hint removido em FASE 5 — respostas not-found retornam apenas dados essenciais
