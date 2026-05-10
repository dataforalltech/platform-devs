"""Configuration for dataquality-mcp server."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Settings loaded from environment (MCP_DATAQUALITY_* prefix)."""

    MCP_DATAQUALITY_BASE_URL: str = "http://localhost:8008/api/v1"
    MCP_DATAQUALITY_API_KEY: str = ""
    MCP_DATAQUALITY_TIMEOUT_SECONDS: int = 60

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
