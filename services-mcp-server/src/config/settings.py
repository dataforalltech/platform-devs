"""Settings do services-mcp (sidecar kind=mcp_http, Model C).

Config de integração ao MCP Gateway central conforme:
  - docs/standards/STD-MCP-001-mcp-gateway-integration-contract.md
  - docs/standards/STD-SEC-006-token-model-c-inner-token.md

`services-mcp` é uma persona **stateful** (mantém um registry de serviços em
PostgreSQL via `ServiceStore`). O "backend" aqui é o próprio store (psycopg2),
não um serviço REST — por isso NÃO há `ServiceApiClient`/`MCP_SERVICE_BASE_URL`/
`MCP_SERVICE_TOKEN` (desvio justificado do esqueleto do template, que assume um
backend HTTP). As tools recebem o `store` diretamente.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# namespace canônico = name_microservice ('platform-services-mcp') menos o
# prefixo 'platform-'. A audiência do inner token DEVE ser exatamente mcp:<namespace>.
NAMESPACE = "services-mcp"


class ServicesSettings(BaseSettings):
    # env_prefix=SERVICES_ preserva as vars legadas (SERVICES_DB_PATH etc.); os
    # campos de integração com o gateway usam validation_alias explícito (sem prefixo).
    model_config = SettingsConfigDict(
        env_prefix="SERVICES_", env_file=".env", extra="ignore", case_sensitive=False
    )

    # ── Integração com o gateway (STD-MCP-001 / STD-SEC-006) ──────────────────
    # Audiência exata que o PEP re-verifica no inner token (a falha de integração
    # nº 1 é audiência divergente → 401).
    mcp_twin_audience: str = Field(default=f"mcp:{NAMESPACE}", validation_alias="MCP_TWIN_AUDIENCE")
    # JWKS do platform-admin (emissor do twin/inner token) — mesma de STD-SEC-006.
    url_admin_twin_jwks: str = Field(default="", validation_alias="URL_ADMIN_TWIN_JWKS")

    # ── HTTP sidecar ──────────────────────────────────────────────────────────
    mcp_port: int = Field(default=7100, validation_alias="MCP_PORT")
    docs_enabled: bool = Field(default=False, validation_alias="DOCS_ENABLED")
    log_level: str = Field(default="INFO", validation_alias="MCP_SERVICE_LOG_LEVEL")

    # ── Registry / tuning das tools (usados diretamente pelo store e tools) ────
    db_path: str = str(Path.home() / ".services-mcp" / "registry.db")
    health_timeout: float = 3.0
    docker_timeout: int = 10  # seconds for docker CLI calls
    # Descoberta eager no boot é opt-in (docker ps + port scan são I/O pesado).
    sync_on_startup: bool = Field(default=False, validation_alias="SERVICES_SYNC_ON_STARTUP")


# Alias de compatibilidade com o padrão canônico (architecture/audit usam `Settings`).
Settings = ServicesSettings


@lru_cache(maxsize=1)
def get_settings() -> ServicesSettings:
    return ServicesSettings()
