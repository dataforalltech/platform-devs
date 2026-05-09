"""Configurações do agent-twin-mcp-server."""
from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentTwinSettings(BaseSettings):
    # ── Token DB ──────────────────────────────────────────────────────────── #
    db_path: str = Field(
        default="~/.config/dataforalltech/agent_twin.db",
        description="Caminho do banco SQLite de tokens.",
    )
    admin_token: str = Field(
        default="",
        description="Token master para operações administrativas (register, revoke, list).",
    )

    # ── HTTP API ──────────────────────────────────────────────────────────── #
    api_port: int = Field(default=7098, description="Porta da HTTP API interna.")
    api_token: str = Field(default="", description="Bearer token para a HTTP API.")
    api_enabled: bool = Field(default=True)

    # ── config-mcp integration ────────────────────────────────────────────── #
    config_mcp_url: str = Field(default="http://127.0.0.1:7099")
    config_mcp_token: str = Field(default="")

    model_config = SettingsConfigDict(
        env_prefix="TWIN_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


def get_settings() -> AgentTwinSettings:
    return AgentTwinSettings()
