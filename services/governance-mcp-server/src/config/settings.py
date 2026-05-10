"""Configuration settings for platform-governance-mcp."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Settings for platform-governance MCP server."""

    base_url: str = Field(
        default="http://localhost:8003",
        description="Base URL of the platform-governance API",
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
        env_prefix="MCP_GOVERNANCE_",
        case_sensitive=False,
    )
