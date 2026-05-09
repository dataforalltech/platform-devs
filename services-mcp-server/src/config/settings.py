from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ServicesSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SERVICES_", env_file=".env", extra="ignore")

    db_path: str = str(Path.home() / ".services-mcp" / "registry.db")
    health_timeout: float = 3.0
    docker_timeout: int = 10  # seconds for docker CLI calls

    # ── HTTP API (sidecar para discovery por outros MCPs) ─────────────────── #
    api_port: int = Field(default=7097, description="Porta da HTTP API interna.")
    api_enabled: bool = Field(default=True, description="Habilitar HTTP API sidecar.")


@lru_cache(maxsize=1)
def get_settings() -> ServicesSettings:
    return ServicesSettings()
