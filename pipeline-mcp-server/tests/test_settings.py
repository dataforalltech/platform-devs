"""Testes de configuração (src/config/settings.py)."""

from __future__ import annotations

from src.config.settings import PipelineSettings, get_settings


def test_defaults():
    s = PipelineSettings(github_token="", github_org="")
    assert s.api_port == 7101
    assert s.api_enabled is True
    assert s.deploy_mcp_url.startswith("http")
    assert s.github_token == ""
    assert s.github_org == ""
    assert s.db_path.endswith("pipeline.db")


def test_env_prefix_override(monkeypatch):
    monkeypatch.setenv("PIPELINE_GITHUB_TOKEN", "ghp_from_env")
    monkeypatch.setenv("PIPELINE_GITHUB_ORG", "env-org")
    monkeypatch.setenv("PIPELINE_API_PORT", "9999")
    s = PipelineSettings()
    assert s.github_token == "ghp_from_env"
    assert s.github_org == "env-org"
    assert s.api_port == 9999


def test_get_settings_is_cached():
    a = get_settings()
    b = get_settings()
    assert a is b
