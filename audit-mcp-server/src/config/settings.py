from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AuditSettings(BaseSettings):
    """Settings for audit-mcp with PostgreSQL support."""

    model_config = SettingsConfigDict(
        env_prefix="AUDIT_",
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

    # Legacy SQLite path (for backward compatibility during migration)
    db_path: str = ".audit.db"

    github_token: str = ""
    github_org: str = "dataforalltech"
    policies_path: str = str(Path(__file__).parent.parent / "policies")
    log_level: str = "INFO"

    @property
    def pg_dsn(self) -> str:
        """Return PostgreSQL connection string."""
        return f"host={self.pg_host} port={self.pg_port} dbname={self.pg_db} user={self.pg_user} password={self.pg_password}"


def get_settings() -> AuditSettings:
    return AuditSettings()
