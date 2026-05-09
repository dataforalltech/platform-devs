from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class TestSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TEST_",
        env_file=".env",
        extra="ignore",
    )

    db_path: str = str(Path.home() / ".test-mcp" / "tests.db")
    default_list_limit: int = 20


def get_settings() -> TestSettings:
    return TestSettings()
