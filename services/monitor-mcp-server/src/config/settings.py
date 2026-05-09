"""Configuration for monitor-mcp server."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Settings loaded from environment (MCP_MONITOR_* prefix)."""

    MCP_MONITOR_BASE_URL: str = "http://localhost:8007/api/v1"
    MCP_MONITOR_API_KEY: str = ""
    MCP_MONITOR_TIMEOUT_SECONDS: int = 30

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
