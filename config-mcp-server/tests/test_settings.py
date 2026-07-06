"""Testes das configurações (pydantic-settings)."""

from __future__ import annotations

from src.config.settings import ConfigMcpSettings, get_settings


class TestSettings:
    def test_defaults_with_required_master_key(self, monkeypatch):
        monkeypatch.setenv("CONFIG_MCP_MASTER_KEY", "some-key")
        # Avoid picking up a local .env file
        settings = ConfigMcpSettings(_env_file=None)
        assert settings.master_key == "some-key"
        assert settings.api_port == 7099
        assert settings.api_enabled is True
        assert settings.api_token == ""

    def test_env_overrides(self, monkeypatch):
        monkeypatch.setenv("CONFIG_MCP_MASTER_KEY", "k")
        monkeypatch.setenv("CONFIG_MCP_API_PORT", "9000")
        monkeypatch.setenv("CONFIG_MCP_API_TOKEN", "secret")
        monkeypatch.setenv("CONFIG_MCP_STORE_PATH", "/tmp/store.json")
        settings = ConfigMcpSettings(_env_file=None)
        assert settings.api_port == 9000
        assert settings.api_token == "secret"
        assert settings.store_path == "/tmp/store.json"

    def test_get_settings_helper(self, monkeypatch):
        monkeypatch.setenv("CONFIG_MCP_MASTER_KEY", "k")
        settings = get_settings()
        assert isinstance(settings, ConfigMcpSettings)
        assert settings.master_key == "k"
