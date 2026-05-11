from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class DocsSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DOCS_", env_file=".env", extra="ignore")

    # PostgreSQL connection settings
    pg_host: str = Field(default="claude-dev", description="PostgreSQL host")
    pg_port: int = Field(default=5432, description="PostgreSQL port")
    pg_db: str = Field(default="app", description="PostgreSQL database name")
    pg_user: str = Field(default="postgres", description="PostgreSQL user")
    pg_password: str = Field(default="postgres_password_local_dev", description="PostgreSQL password")
    pg_min_conn: int = Field(default=2, description="Minimum pool connections")
    pg_max_conn: int = Field(default=10, description="Maximum pool connections")

    # Docs-specific settings
    http_timeout: float = 10.0  # para check_links externo
    stale_days_threshold: int = 90  # docs sem update em X dias = stale
    check_external_links: bool = False  # httpx em links externos (lento)
    max_file_size_kb: int = 500  # ignora arquivos maiores que X KB no scan
    coverage_threshold: float = 80.0  # % mínimo de docs para score máximo

    @property
    def pg_dsn(self) -> str:
        """Return PostgreSQL connection string."""
        return f"host={self.pg_host} port={self.pg_port} dbname={self.pg_db} user={self.pg_user} password={self.pg_password}"


@lru_cache(maxsize=1)
def get_settings() -> DocsSettings:
    return DocsSettings()
