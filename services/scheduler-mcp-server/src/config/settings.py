"""Configuration settings for platform-scheduler-mcp."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Settings for platform-scheduler MCP server."""

    base_url: str = Field(
        default="http://localhost:8005",
        description="Base URL of the platform-scheduler API",
    )
    internal_token: str = Field(
        default="",
        description="X-Internal-Token for service-to-service authentication",
    )
    log_level: str = Field(
        default="INFO",
        description="Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)",
    )
    request_timeout: float = Field(
        default=30.0,
        description="HTTP request timeout in seconds",
    )

    model_config = SettingsConfigDict(
        env_prefix="MCP_SCHEDULER_",
        case_sensitive=False,
    )
