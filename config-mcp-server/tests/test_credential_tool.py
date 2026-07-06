"""Testes adicionais de credential_tool (paths não cobertos por test_store)."""

from __future__ import annotations

import getpass

from src.tools.credential_tool import set_credential, set_credential_secure


class TestSetCredentialDescription:
    def test_set_credential_with_description(self, store):
        result = set_credential(
            store, "credentials.acr", "ACR_USER", "u", description="ACR admin user"
        )
        assert result["success"] is True
        assert result["description"] == "ACR admin user"
        assert store.get("credentials.acr", "ACR_USER") == "u"

    def test_set_credential_without_description(self, store):
        result = set_credential(store, "credentials.acr", "ACR_USER", "u")
        assert "description" not in result


class TestSetCredentialSecureCancel:
    def test_keyboard_interrupt_is_handled(self, store, monkeypatch):
        def boom(prompt=""):
            raise KeyboardInterrupt

        monkeypatch.setattr(getpass, "getpass", boom)
        result = set_credential_secure(store, "credentials.e2e", "PASSWORD")
        assert result["success"] is False
        assert "cancelada" in result["error"].lower()
        assert store.get("credentials.e2e", "PASSWORD") is None

    def test_eof_error_is_handled(self, store, monkeypatch):
        def boom(prompt=""):
            raise EOFError

        monkeypatch.setattr(getpass, "getpass", boom)
        result = set_credential_secure(store, "credentials.e2e", "PASSWORD")
        assert result["success"] is False
