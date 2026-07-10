"""Settings do docs-mcp (sidecar mcp_http, Model C).

Config de integração ao MCP Gateway central conforme:
  - docs/standards/STD-MCP-001-mcp-gateway-integration-contract.md
  - docs/standards/STD-SEC-006-token-model-c-inner-token.md

`docs-mcp` indexa/valida/audita documentação e persiste histórico num store
PostgreSQL **próprio** (src/db/store.py) — não conversa com um backend REST via
HTTP, então NÃO há `ServiceApiClient`/`MCP_SERVICE_BASE_URL`/`MCP_SERVICE_TOKEN`
aqui (deviação justificada do esqueleto do template, que assume um backend HTTP).
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# namespace canônico = name_microservice ('platform-docs-mcp') menos o prefixo
# 'platform-'. A audiência do inner token DEVE ser exatamente mcp:<namespace>.
NAMESPACE = "docs-mcp"


class Settings(BaseSettings):
    # env_prefix DOCS_ preserva os nomes das envs de banco (DOCS_PG_*); os campos
    # do gateway usam validation_alias absoluto (bypassa o prefixo).
    model_config = SettingsConfigDict(
        env_prefix="DOCS_", env_file=".env", extra="ignore", case_sensitive=False
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

    # ── PostgreSQL (store de índice + histórico de auditoria) ─────────────────
    pg_host: str = Field(default="claude-dev", description="PostgreSQL host")
    pg_port: int = Field(default=5432, description="PostgreSQL port")
    pg_db: str = Field(default="app", description="PostgreSQL database name")
    pg_user: str = Field(default="postgres", description="PostgreSQL user")
    pg_password: str = Field(default="postgres_password_local_dev", description="PostgreSQL password")
    pg_min_conn: int = Field(default=2, description="Minimum pool connections")
    pg_max_conn: int = Field(default=10, description="Maximum pool connections")

    # ── Docs-specific ─────────────────────────────────────────────────────────
    http_timeout: float = 10.0  # para check_links externo
    stale_days_threshold: int = 90  # docs sem update em X dias = stale
    check_external_links: bool = False  # httpx em links externos (lento)
    max_file_size_kb: int = 500  # ignora arquivos maiores que X KB no scan
    coverage_threshold: float = 80.0  # % mínimo de docs para score máximo

    @property
    def pg_dsn(self) -> str:
        """Return PostgreSQL connection string."""
        return (
            f"host={self.pg_host} port={self.pg_port} dbname={self.pg_db} "
            f"user={self.pg_user} password={self.pg_password}"
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


# Backward-compat: o store e as tools ainda tipam `DocsSettings`.
DocsSettings = Settings
