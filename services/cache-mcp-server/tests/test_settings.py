"""Tests for settings configuration."""

import os
import pytest
from unittest.mock import patch

from src.config.settings import Settings


def test_settings_defaults() -> None:
    """Test default settings."""
    with patch.dict(os.environ, {}, clear=True):
        settings = Settings()

        assert settings.base_url == "http://localhost:8025"
        assert settings.internal_token == ""
        assert settings.log_level == "INFO"
        assert settings.request_timeout == 30.0


def test_settings_from_env() -> None:
    """Test settings from environment variables."""
    env_vars = {
        "MCP_CACHE_BASE_URL": "http://custom:9000",
        "MCP_CACHE_INTERNAL_TOKEN": "custom-token",
        "MCP_CACHE_LOG_LEVEL": "DEBUG",
        "MCP_CACHE_REQUEST_TIMEOUT": "60.0",
    }

    with patch.dict(os.environ, env_vars, clear=True):
        settings = Settings()

        assert settings.base_url == "http://custom:9000"
        assert settings.internal_token == "custom-token"
        assert settings.log_level == "DEBUG"
        assert settings.request_timeout == 60.0


def test_settings_partial_env() -> None:
    """Test settings with partial environment variables."""
    with patch.dict(os.environ, {"MCP_CACHE_BASE_URL": "http://prod:8025"}, clear=True):
        settings = Settings()

        assert settings.base_url == "http://prod:8025"
        assert settings.internal_token == ""
        assert settings.log_level == "INFO"
        assert settings.request_timeout == 30.0


def test_settings_case_insensitive() -> None:
    """Test that settings are case-insensitive."""
    with patch.dict(
        os.environ,
        {"mcp_cache_log_level": "WARNING"},
        clear=True,
    ):
        settings = Settings()

        assert settings.log_level == "WARNING"


def test_settings_explicit_values() -> None:
    """Test settings with explicit values."""
    settings = Settings(
        base_url="http://localhost:9999",
        internal_token="explicit-token",
        log_level="ERROR",
        request_timeout=45.0,
    )

    assert settings.base_url == "http://localhost:9999"
    assert settings.internal_token == "explicit-token"
    assert settings.log_level == "ERROR"
    assert settings.request_timeout == 45.0


def test_settings_prefix() -> None:
    """Test that settings use correct env prefix."""
    # Should NOT pick up non-prefixed variables
    with patch.dict(
        os.environ,
        {
            "BASE_URL": "http://wrong:8025",
            "MCP_CACHE_BASE_URL": "http://correct:8025",
        },
        clear=True,
    ):
        settings = Settings()

        assert settings.base_url == "http://correct:8025"
