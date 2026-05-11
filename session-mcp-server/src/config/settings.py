from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class SessionSettings(BaseSettings):
    """Settings do session-mcp.

    Configuração de banco PostgreSQL e defaults de convenção.
    """

    model_config = SettingsConfigDict(
        env_prefix="SESSION_",
        env_file=".env",
        extra="ignore",
    )

    # PostgreSQL connection settings
    pg_host: str = Field(default="claude-dev", description="PostgreSQL host")
    pg_port: int = Field(default=5432, description="PostgreSQL port")
    pg_db: str = Field(default="app", description="PostgreSQL database name")
    pg_user: str = Field(default="postgres", description="PostgreSQL user")
    pg_password: str = Field(default="postgres_password_local_dev", description="PostgreSQL password")
    pg_min_conn: int = Field(default=2, description="Minimum pool connections")
    pg_max_conn: int = Field(default=10, description="Maximum pool connections")

    # Session management
    max_active_sessions: int = Field(default=50)
    default_list_limit: int = Field(default=20)
    default_base_branch: str = Field(
        default="develop",
        description="Branch base sugerida quando o agente cria a branch da sessão via deploy-mcp.",
    )

    @property
    def pg_dsn(self) -> str:
        """Return PostgreSQL connection string."""
        return f"host={self.pg_host} port={self.pg_port} dbname={self.pg_db} user={self.pg_user} password={self.pg_password}"


def get_settings() -> SessionSettings:
    return SessionSettings()
