"""Testes adicionais do ConfigStore — cobre paths de erro, listagem e namespaces."""

from __future__ import annotations

import pytest

from src.knowledge.encryptor import EncryptionError
from src.knowledge.store import ConfigStore, StoreError


class TestListingAndNamespaces:
    def test_list_keys_all_namespaces(self, store):
        store.set("env.dev", "A", "1")
        store.set("credentials.acr", "ACR_USER", "u")
        keys = store.list_keys()
        assert keys["env.dev"] == ["A"]
        assert keys["credentials.acr"] == ["ACR_USER"]

    def test_list_keys_missing_namespace_returns_empty(self, store):
        assert store.list_keys("does.not.exist") == {"does.not.exist": []}

    def test_list_namespaces_sorted(self, store):
        store.set("zeta", "k", "v")
        store.set("alpha", "k", "v")
        assert store.list_namespaces() == ["alpha", "zeta"]

    def test_namespace_exists(self, store):
        assert store.namespace_exists("ns") is False
        store.set("ns", "k", "v")
        assert store.namespace_exists("ns") is True

    def test_delete_namespace_existing(self, store):
        store.set("ns", "k1", "v1")
        store.set("ns", "k2", "v2")
        assert store.delete_namespace("ns") is True
        assert store.namespace_exists("ns") is False

    def test_delete_namespace_missing(self, store):
        assert store.delete_namespace("nope") is False

    def test_get_namespace_empty_when_missing(self, store):
        assert store.get_namespace("missing") == {}


class TestErrorPaths:
    def test_get_decrypt_error_raises_store_error(self, store, monkeypatch):
        store.set("ns", "k", "v")

        def boom(_token):
            raise EncryptionError("bad token")

        monkeypatch.setattr(store._enc, "decrypt", boom)
        with pytest.raises(StoreError):
            store.get("ns", "k")

    def test_get_namespace_marks_decrypt_error(self, store, monkeypatch):
        store.set("ns", "k", "v")

        def boom(_token):
            raise EncryptionError("bad token")

        monkeypatch.setattr(store._enc, "decrypt", boom)
        result = store.get_namespace("ns")
        assert result["k"] == "<decrypt_error>"

    def test_load_corrupt_json_raises(self, tmp_path, encryptor):
        path = tmp_path / "corrupt.enc.json"
        path.write_text("{not valid json", encoding="utf-8")
        with pytest.raises(StoreError):
            ConfigStore(str(path), encryptor)

    def test_save_persists_encrypted_not_plaintext(self, tmp_path, encryptor):
        path = tmp_path / "s.enc.json"
        s = ConfigStore(str(path), encryptor)
        s.set("credentials.x", "TOKEN", "plaintext_secret")
        raw = path.read_text(encoding="utf-8")
        assert "plaintext_secret" not in raw


class TestPostgresSyncDisabledByDefault:
    def test_postgres_sync_none_when_env_unset(self, store, monkeypatch):
        monkeypatch.delenv("POSTGRES_SYNC_ENABLED", raising=False)
        # store fixture already built with sync disabled
        assert store._postgres_sync is None

    def test_set_and_delete_do_not_call_sync_when_disabled(self, store):
        store.set("ns", "k", "v")
        assert store.delete("ns", "k") is True
