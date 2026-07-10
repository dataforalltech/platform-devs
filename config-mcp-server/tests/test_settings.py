"""Testes das configurações (pydantic-settings, Model C)."""

from __future__ import annotations

import pytest

from src.config.secrets import load_secret
from src.config.settings import NAMESPACE, ConfigMcpSettings, Settings, get_settings


class TestSettings:
    def test_namespace_and_default_audience(self):
        assert NAMESPACE == "config-mcp"
        settings = Settings(_env_file=None)
        # audiência default = mcp:<namespace> (a falha de integração nº 1)
        assert settings.mcp_twin_audience == "mcp:config-mcp"

    def test_sidecar_defaults(self, monkeypatch):
        # o ambiente do dev pode exportar CONFIG_MCP_MASTER_KEY — isole o default
        monkeypatch.delenv("CONFIG_MCP_MASTER_KEY", raising=False)
        settings = Settings(_env_file=None)
        assert settings.mcp_port == 7100
        assert settings.docs_enabled is False
        assert settings.url_admin_twin_jwks == ""
        assert settings.master_key == ""

    def test_env_overrides_gateway_and_store(self, monkeypatch):
        monkeypatch.setenv("MCP_TWIN_AUDIENCE", "mcp:custom")
        monkeypatch.setenv("URL_ADMIN_TWIN_JWKS", "http://admin/.well-known/jwks.json")
        monkeypatch.setenv("MCP_PORT", "9000")
        monkeypatch.setenv("DOCS_ENABLED", "true")
        monkeypatch.setenv("CONFIG_MCP_MASTER_KEY", "k")
        monkeypatch.setenv("CONFIG_MCP_STORE_PATH", "/tmp/store.json")
        settings = Settings(_env_file=None)
        assert settings.mcp_twin_audience == "mcp:custom"
        assert settings.url_admin_twin_jwks.endswith("jwks.json")
        assert settings.mcp_port == 9000
        assert settings.docs_enabled is True
        assert settings.master_key == "k"
        assert settings.store_path == "/tmp/store.json"

    def test_backcompat_alias(self):
        assert ConfigMcpSettings is Settings

    def test_get_settings_is_cached(self, monkeypatch):
        get_settings.cache_clear()
        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2


class TestRuntimeEnv:
    def test_default_local(self):
        assert Settings(_env_file=None).runtime_env == "local"

    def test_normalizes_case_and_whitespace(self):
        assert Settings(RUNTIME_ENV="  CLOUD ", _env_file=None).runtime_env == "cloud"

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            Settings(RUNTIME_ENV="prod", _env_file=None)


class TestEnforceSecurityInvariants:
    def _s(self, **kw):
        base = {
            "MCP_TWIN_AUDIENCE": "mcp:config-mcp",
            "URL_ADMIN_TWIN_JWKS": "http://admin/jwks.json",
            "CONFIG_MCP_MASTER_KEY": "k",
            "_env_file": None,
        }
        base.update(kw)
        return Settings(**base)

    def test_local_ok(self):
        self._s(RUNTIME_ENV="local").enforce_security_invariants()  # não levanta

    def test_docs_enabled_rejected(self):
        with pytest.raises(RuntimeError, match="STD-SEC-001"):
            self._s(DOCS_ENABLED="true").enforce_security_invariants()

    def test_bad_audience_rejected(self):
        with pytest.raises(RuntimeError, match="STD-SEC-006"):
            self._s(MCP_TWIN_AUDIENCE="config-mcp").enforce_security_invariants()

    def test_cloud_requires_jwks(self):
        with pytest.raises(RuntimeError, match="URL_ADMIN_TWIN_JWKS"):
            self._s(RUNTIME_ENV="cloud", URL_ADMIN_TWIN_JWKS="").enforce_security_invariants()

    def test_cloud_requires_master_key(self, monkeypatch):
        monkeypatch.delenv("VAULT_ADDR", raising=False)
        monkeypatch.delenv("CONFIG_MCP_MASTER_KEY", raising=False)
        with pytest.raises(RuntimeError, match="STD-SEC-004"):
            self._s(RUNTIME_ENV="cloud", CONFIG_MCP_MASTER_KEY="").enforce_security_invariants()

    def test_cloud_ok_with_all(self):
        self._s(RUNTIME_ENV="cloud").enforce_security_invariants()  # não levanta


class TestLoadSecret:
    def test_no_vault_returns_env_value(self, monkeypatch):
        monkeypatch.delenv("VAULT_ADDR", raising=False)
        assert load_secret("CONFIG_MCP_MASTER_KEY", "from-field") == "from-field"

    def test_resolve_master_key_uses_field(self, monkeypatch):
        monkeypatch.delenv("VAULT_ADDR", raising=False)
        s = Settings(CONFIG_MCP_MASTER_KEY="abc", _env_file=None)
        assert s.resolve_master_key() == "abc"

    def test_vault_success(self, monkeypatch):
        monkeypatch.setenv("VAULT_ADDR", "http://vault:8200")

        class _FakeClient:
            def get_secret(self, key):
                return "from-vault"

        fake_mod = type("m", (), {"VaultSecretsClient": _FakeClient})
        monkeypatch.setitem(__import__("sys").modules, "platform_crypto", fake_mod)
        assert load_secret("CONFIG_MCP_MASTER_KEY", "from-field") == "from-vault"

    def test_vault_unavailable_falls_back(self, monkeypatch):
        # VAULT_ADDR setado mas a lib não existe → degradação graciosa p/ o env.
        monkeypatch.setenv("VAULT_ADDR", "http://vault:8200")
        monkeypatch.delitem(__import__("sys").modules, "platform_crypto", raising=False)
        assert load_secret("CONFIG_MCP_MASTER_KEY", "from-field") == "from-field"

    def test_vault_empty_falls_back(self, monkeypatch):
        monkeypatch.setenv("VAULT_ADDR", "http://vault:8200")

        class _EmptyClient:
            def get_secret(self, key):
                return ""

        fake_mod = type("m", (), {"VaultSecretsClient": _EmptyClient})
        monkeypatch.setitem(__import__("sys").modules, "platform_crypto", fake_mod)
        assert load_secret("CONFIG_MCP_MASTER_KEY", "from-field") == "from-field"
