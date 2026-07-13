"""Config do backend-mcp."""

from __future__ import annotations

from .settings import NAMESPACE, BackendSettings, Settings, get_settings, load_secret

__all__ = ["NAMESPACE", "BackendSettings", "Settings", "get_settings", "load_secret"]
