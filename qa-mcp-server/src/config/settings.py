from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class QASettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="QA_", env_file=".env", extra="ignore")

    db_path: str = str(Path.home() / ".qa-mcp" / "runs.db")
    screenshots_dir: str = str(Path.home() / ".qa-mcp" / "screenshots")
    baselines_dir: str = str(Path.home() / ".qa-mcp" / "baselines")

    http_timeout: float = 10.0
    browser_timeout: int = 30_000  # ms para Playwright
    subprocess_timeout: int = 120  # segundos para processos externos

    default_browser: str = "chromium"  # chromium | firefox | webkit
    headless: bool = True

    complexity_threshold: int = 10  # CC > 10 é "complexo"
    coverage_threshold: float = 80.0  # % mínimo de cobertura


@lru_cache(maxsize=1)
def get_settings() -> QASettings:
    return QASettings()
