"""Configuration for analytics-mcp server."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Settings loaded from environment (MCP_ANALYTICS_* prefix)."""

    MCP_ANALYTICS_BASE_URL: str = "http://localhost:8002/api/v1"
    MCP_ANALYTICS_API_KEY: str = ""
    MCP_ANALYTICS_TIMEOUT_SECONDS: int = 60
    MCP_ANALYTICS_VERIFY_SSL: bool = True

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
