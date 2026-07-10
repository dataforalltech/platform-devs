"""Testes das configurações (pydantic-settings, Model C)."""

from __future__ import annotations

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
