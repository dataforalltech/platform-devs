"""Settings do pipeline-mcp (sidecar mcp_http, Model C).

Config de integração ao MCP Gateway central conforme:
  - docs/standards/STD-MCP-001-mcp-gateway-integration-contract.md
  - docs/standards/STD-SEC-006-token-model-c-inner-token.md

`pipeline-mcp` é uma persona **stateful** (mantém estado de pipelines/gates/promoções
num PostgreSQL via `PipelineStore`) e fala com a **GitHub REST API** para criar/mergiar
PRs. Não há um Trinity backend HTTP intermediário, então NÃO há `ServiceApiClient`/
`MCP_SERVICE_BASE_URL`/`MCP_SERVICE_TOKEN` — a persistência é direta (psycopg2, `PG_DSN`)
e o GitHub é chamado com `PIPELINE_GITHUB_TOKEN`/`PIPELINE_GITHUB_ORG`.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# namespace canônico = name_microservice ('platform-pipeline-mcp') menos o
# prefixo 'platform-'. A audiência do inner token DEVE ser exatamente mcp:<namespace>.
NAMESPACE = "pipeline-mcp"


class PipelineSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

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

    # ── GitHub (criação/merge de PRs durante promoções) ───────────────────────
    github_token: str = Field(default="", validation_alias="PIPELINE_GITHUB_TOKEN")
    github_org: str = Field(default="", validation_alias="PIPELINE_GITHUB_ORG")


# Alias de compatibilidade com o padrão do template (Settings).
Settings = PipelineSettings


@lru_cache(maxsize=1)
def get_settings() -> PipelineSettings:
    return PipelineSettings()
