"""Testes de configuração (src/config/settings.py) — sidecar mcp_http (Model C)."""

from __future__ import annotations

from src.config import NAMESPACE, PipelineSettings, Settings, get_settings


def test_namespace_is_canonical():
    # name_microservice ('platform-pipeline-mcp') menos o prefixo 'platform-'.
    assert NAMESPACE == "pipeline-mcp"


def test_settings_alias_points_to_pipeline_settings():
    assert Settings is PipelineSettings


def test_gateway_defaults():
    s = PipelineSettings(github_token="", github_org="")
    # audiência do inner token = mcp:<namespace> (a falha de integração nº 1)
    assert s.mcp_twin_audience == "mcp:pipeline-mcp"
    # porta canônica do sidecar
    assert s.mcp_port == 7100
    # /docs desabilitado em todo ambiente (HTTP-01)
    assert s.docs_enabled is False
    assert s.log_level == "INFO"
    # JWKS do platform-admin: vazio por padrão (obrigatório em runtime)
    assert s.url_admin_twin_jwks == ""


def test_github_defaults_empty():
    s = PipelineSettings(github_token="", github_org="")
    assert s.github_token == ""
    assert s.github_org == ""


def test_gateway_env_override(monkeypatch):
    monkeypatch.setenv("MCP_TWIN_AUDIENCE", "mcp:custom")
    monkeypatch.setenv("URL_ADMIN_TWIN_JWKS", "https://admin.local/jwks.json")
    monkeypatch.setenv("MCP_PORT", "7999")
    monkeypatch.setenv("MCP_SERVICE_LOG_LEVEL", "DEBUG")
    s = PipelineSettings()
    assert s.mcp_twin_audience == "mcp:custom"
    assert s.url_admin_twin_jwks == "https://admin.local/jwks.json"
    assert s.mcp_port == 7999
    assert s.log_level == "DEBUG"


def test_github_env_override(monkeypatch):
    monkeypatch.setenv("PIPELINE_GITHUB_TOKEN", "ghp_from_env")
    monkeypatch.setenv("PIPELINE_GITHUB_ORG", "env-org")
    s = PipelineSettings()
    assert s.github_token == "ghp_from_env"
    assert s.github_org == "env-org"


def test_get_settings_is_cached():
    get_settings.cache_clear()
    a = get_settings()
    b = get_settings()
    assert a is b
    get_settings.cache_clear()
