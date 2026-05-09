from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class PipelineSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PIPELINE_", env_file=".env", extra="ignore")

    db_path: str = str(Path.home() / ".pipeline-mcp" / "pipeline.db")
    api_port: int = Field(default=7101, description="Porta da HTTP API interna.")
    api_enabled: bool = Field(default=True, description="Habilitar HTTP API sidecar.")
    deploy_mcp_url: str = Field(
        default="http://127.0.0.1:7100",
        description="URL base do deploy-mcp para operações de merge.",
    )
    github_token: str = Field(
        default="",
        description="GitHub token para auto-aprovação de PRs (PIPELINE_GITHUB_TOKEN ou DEPLOY_GITHUB_TOKEN).",
    )
    github_org: str = Field(
        default="",
        description="Organização GitHub (PIPELINE_GITHUB_ORG ou DEPLOY_GITHUB_ORG).",
    )


@lru_cache(maxsize=1)
def get_settings() -> PipelineSettings:
    return PipelineSettings()
