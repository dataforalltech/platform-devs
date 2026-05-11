"""Configurações do agent-twin-mcp-server."""
from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentTwinSettings(BaseSettings):
    # ── PostgreSQL Token Store ────────────────────────────────────────────── #
    pg_host: str = Field(default="claude-dev", description="PostgreSQL host")
    pg_port: int = Field(default=5432, description="PostgreSQL port")
    pg_db: str = Field(default="app", description="PostgreSQL database name")
    pg_user: str = Field(default="postgres", description="PostgreSQL user")
    pg_password: str = Field(default="postgres_password_local_dev", description="PostgreSQL password")
    pg_min_conn: int = Field(default=2, description="Minimum pool connections")
    pg_max_conn: int = Field(default=10, description="Maximum pool connections")

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

    @property
    def pg_dsn(self) -> str:
        """Return PostgreSQL connection string."""
        return f"host={self.pg_host} port={self.pg_port} dbname={self.pg_db} user={self.pg_user} password={self.pg_password}"


def get_settings() -> AgentTwinSettings:
    return AgentTwinSettings()
