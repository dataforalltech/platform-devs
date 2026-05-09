"""Configurações do config-mcp-server."""
from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigMcpSettings(BaseSettings):
    # ── Store ─────────────────────────────────────────────────────────────── #
    store_path: str = Field(
        default="~/.config/dataforalltech/config.enc.json",
        description="Caminho do arquivo de store encriptado.",
    )
    master_key: str = Field(
        description="Chave Fernet para encriptar/decriptar valores no store.",
    )

    # ── HTTP API ──────────────────────────────────────────────────────────── #
    api_port: int = Field(default=7099, description="Porta da HTTP API interna.")
    api_token: str = Field(
        default="",
        description="Token Bearer para autenticação da HTTP API. Deixe vazio para desabilitar auth.",
    )
    api_enabled: bool = Field(default=True, description="Habilitar HTTP API.")

    model_config = SettingsConfigDict(
        env_prefix="CONFIG_MCP_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


def get_settings() -> ConfigMcpSettings:
    return ConfigMcpSettings()  # type: ignore[call-arg]
