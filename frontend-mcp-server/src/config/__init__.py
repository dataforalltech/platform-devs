"""Config do frontend-mcp."""

from __future__ import annotations

from .settings import NAMESPACE, FrontendSettings, Settings, get_settings, load_secret

__all__ = ["NAMESPACE", "FrontendSettings", "Settings", "get_settings", "load_secret"]
