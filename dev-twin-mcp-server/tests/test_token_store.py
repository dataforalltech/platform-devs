"""Testes do TokenStore."""
from __future__ import annotations

import time

import pytest

from src.knowledge.token_store import TokenStore, TokenStoreError


class TestTokenStore:
    def test_register_and_validate(self, store):
        record = store.register(name="Alice", email="alice@test.com")
        assert record["token"]
        validated = store.validate(record["token"])
        assert validated is not None
        assert validated["name"] == "Alice"
        assert validated["email"] == "alice@test.com"
        assert validated["role"] == "developer"

    def test_invalid_token_returns_none(self, store):
        assert store.validate("invalid-token-xyz") is None

    def test_revoke_by_token(self, store):
        record = store.register(name="Bob", email="bob@test.com")
        token = record["token"]
        result = store.revoke(token)
        assert result["revoked"] is True
        assert store.validate(token) is None

    def test_revoke_by_user_id(self, store):
        record = store.register(name="Carol", email="carol@test.com")
        result = store.revoke(record["user_id"])
        assert result["revoked"] is True
        assert store.validate(record["token"]) is None

    def test_revoke_missing_returns_false(self, store):
        result = store.revoke("nonexistent")
        assert result["revoked"] is False
        assert result["affected"] == 0

    def test_rotate_token(self, store):
        original = store.register(name="Dave", email="dave@test.com")
        new = store.rotate(original["user_id"])
        # Old token invalid
        assert store.validate(original["token"]) is None
        # New token valid
        assert store.validate(new["token"]) is not None
        assert new["name"] == "Dave"

    def test_list_all_excludes_revoked_by_default(self, store):
        a = store.register(name="A", email="a@test.com")
        b = store.register(name="B", email="b@test.com")
        store.revoke(b["token"])
        records = store.list_all()
        names = [r["name"] for r in records]
        assert "A" in names
        assert "B" not in names

    def test_list_all_include_revoked(self, store):
        a = store.register(name="A", email="a@test.com")
        store.revoke(a["token"])
        records = store.list_all(include_revoked=True)
        assert any(r["name"] == "A" for r in records)

    def test_list_all_hides_token_values(self, store):
        record = store.register(name="E", email="e@test.com")
        records = store.list_all()
        for r in records:
            assert "token" not in r

    def test_touch_updates_last_used_at(self, store):
        record = store.register(name="F", email="f@test.com")
        store.touch(record["user_id"])
        validated = store.validate(record["token"])
        assert validated["last_used_at"] is not None

    def test_scopes_stored_correctly(self, store):
        record = store.register(
            name="G", email="g@test.com", scopes=["deploy", "qa"]
        )
        import json
        validated = store.validate(record["token"])
        assert json.loads(validated["scopes"]) == ["deploy", "qa"]

    def test_environment_stored_correctly(self, store):
        record = store.register(
            name="H", email="h@test.com", environment="production"
        )
        validated = store.validate(record["token"])
        assert validated["environment"] == "production"

    def test_tenant_id_stored_correctly(self, store):
        record = store.register(
            name="I", email="i@test.com", tenant_id="tenant_abc123"
        )
        assert record["tenant_id"] == "tenant_abc123"
        validated = store.validate(record["token"])
        assert validated["tenant_id"] == "tenant_abc123"

    def test_tenant_id_defaults_to_none(self, store):
        record = store.register(name="J", email="j@test.com")
        assert record["tenant_id"] is None
        validated = store.validate(record["token"])
        assert validated["tenant_id"] is None

    def test_rotate_preserves_tenant_id(self, store):
        original = store.register(name="K", email="k@test.com", tenant_id="tenant_xyz")
        rotated = store.rotate(original["user_id"])
        assert rotated["tenant_id"] == "tenant_xyz"
