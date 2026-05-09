"""Configuration for dai-mcp server."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Settings loaded from environment (MCP_DAI_* prefix)."""

    MCP_DAI_BASE_URL: str = "http://localhost:5003/api/v1"
    MCP_DAI_API_KEY: str = ""
    MCP_DAI_TIMEOUT_SECONDS: int = 180

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
