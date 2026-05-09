"""Configuration for pipeline-mcp server."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Settings loaded from environment (MCP_PIPELINE_* prefix)."""

    MCP_PIPELINE_BASE_URL: str = "http://localhost:8003/api/v1"
    MCP_PIPELINE_API_KEY: str = ""
    MCP_PIPELINE_TIMEOUT_SECONDS: int = 120

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
