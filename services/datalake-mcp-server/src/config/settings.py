"""Configuration for datalake-mcp server."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Settings loaded from environment (MCP_DATALAKE_* prefix)."""

    # Service configuration
    MCP_DATALAKE_SERVICE_NAME: str = "datalake-mcp"
    MCP_DATALAKE_SERVICE_HOST: str = "localhost"
    MCP_DATALAKE_SERVICE_PORT: int = 8005

    # Datalake API
    MCP_DATALAKE_BASE_URL: str = "http://localhost:8005/api/v1"
    MCP_DATALAKE_API_KEY: str = ""
    MCP_DATALAKE_TIMEOUT_SECONDS: int = 30

    # HTTP Client
    MCP_DATALAKE_VERIFY_SSL: bool = True
    MCP_DATALAKE_MAX_RETRIES: int = 3

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True


settings = Settings()
