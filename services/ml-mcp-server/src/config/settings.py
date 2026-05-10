"""Configuration for ml-mcp server."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Settings loaded from environment (MCP_ML_* prefix)."""

    # Service configuration
    MCP_ML_SERVICE_NAME: str = "ml-mcp"
    MCP_ML_SERVICE_HOST: str = "localhost"
    MCP_ML_SERVICE_PORT: int = 8006

    # ML API
    MCP_ML_BASE_URL: str = "http://localhost:8006/api/v1"
    MCP_ML_API_KEY: str = ""
    MCP_ML_TIMEOUT_SECONDS: int = 60  # Training can take longer

    # HTTP Client
    MCP_ML_VERIFY_SSL: bool = True
    MCP_ML_MAX_RETRIES: int = 3

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True


settings = Settings()
