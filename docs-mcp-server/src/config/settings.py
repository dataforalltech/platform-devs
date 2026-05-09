from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class DocsSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DOCS_", env_file=".env", extra="ignore")

    db_path: str = str(Path.home() / ".docs-mcp" / "audits.db")
    http_timeout: float = 10.0  # para check_links externo
    stale_days_threshold: int = 90  # docs sem update em X dias = stale
    check_external_links: bool = False  # httpx em links externos (lento)
    max_file_size_kb: int = 500  # ignora arquivos maiores que X KB no scan
    coverage_threshold: float = 80.0  # % mínimo de docs para score máximo


@lru_cache(maxsize=1)
def get_settings() -> DocsSettings:
    return DocsSettings()
