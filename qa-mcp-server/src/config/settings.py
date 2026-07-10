"""Settings do qa-mcp (sidecar mcp_http, Model C).

Config de integração ao MCP Gateway central conforme:
  - docs/standards/STD-MCP-001-mcp-gateway-integration-contract.md
  - docs/standards/STD-SEC-006-token-model-c-inner-token.md

`qa-mcp` executa testes/análises e PERSISTE runs num store PostgreSQL local
(src/db/store.py) — não fala com um backend REST (não há `ServiceApiClient`/
`MCP_SERVICE_BASE_URL`). Os campos QA_* originais (db_path, screenshots_dir, …)
são preservados; acrescentam-se os campos canônicos do Model C.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# namespace canônico = name_microservice ('platform-qa-mcp') menos o prefixo
# 'platform-'. A audiência do inner token DEVE ser exatamente mcp:<namespace>.
NAMESPACE = "qa-mcp"


class QASettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="QA_",
        env_file=".env",
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,
    )

    # ── Integração com o gateway (STD-MCP-001 / STD-SEC-006) ──────────────────
    # Audiência exata que o PEP re-verifica no inner token (a falha de integração
    # nº 1 é audiência divergente → 401). Aliases SEM o prefixo QA_.
    mcp_twin_audience: str = Field(default=f"mcp:{NAMESPACE}", validation_alias="MCP_TWIN_AUDIENCE")
    # JWKS do platform-admin (emissor do twin/inner token) — mesma de STD-SEC-006.
    url_admin_twin_jwks: str = Field(default="", validation_alias="URL_ADMIN_TWIN_JWKS")

    # ── HTTP sidecar ──────────────────────────────────────────────────────────
    mcp_port: int = Field(default=7100, validation_alias="MCP_PORT")
    docs_enabled: bool = Field(default=False, validation_alias="DOCS_ENABLED")
    log_level: str = Field(default="INFO", validation_alias="MCP_SERVICE_LOG_LEVEL")

    # ── QA-específico (preservado) ────────────────────────────────────────────
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


# Alias de compatibilidade com o padrão canônico (architecture usa `Settings`).
Settings = QASettings


@lru_cache(maxsize=1)
def get_settings() -> QASettings:
    return QASettings()
