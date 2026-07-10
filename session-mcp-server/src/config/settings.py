"""Settings do session-mcp (sidecar mcp_http, Model C).

Config de integração ao MCP Gateway central conforme:
  - docs/standards/STD-MCP-001-mcp-gateway-integration-contract.md
  - docs/standards/STD-SEC-006-token-model-c-inner-token.md

`session-mcp` é stateful: persiste sessões/tasks/sugestões/decisões num store
(``SessionStore``). Por isso mantém as settings de backend (prefixo ``SESSION_``)
e injeta o store no dispatcher. As settings do gateway (audiência do inner token,
JWKS do platform-admin, porta do sidecar) usam ``validation_alias`` próprio — o
prefixo ``SESSION_`` NÃO se aplica a campos com alias.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# namespace canônico = name_microservice ('platform-session-mcp') menos o prefixo
# 'platform-'. A audiência do inner token DEVE ser exatamente mcp:<namespace>.
NAMESPACE = "session-mcp"


class SessionSettings(BaseSettings):
    """Settings do session-mcp: gateway (Model C) + backend de sessões."""

    model_config = SettingsConfigDict(
        env_prefix="SESSION_",
        env_file=".env",
        extra="ignore",
        case_sensitive=False,
    )

    # ── Integração com o gateway (STD-MCP-001 / STD-SEC-006) ──────────────────
    # Audiência exata que o PEP re-verifica no inner token (a falha de integração
    # nº 1 é audiência divergente → 401). validation_alias ignora env_prefix.
    mcp_twin_audience: str = Field(default=f"mcp:{NAMESPACE}", validation_alias="MCP_TWIN_AUDIENCE")
    # JWKS do platform-admin (emissor do twin/inner token) — mesma de STD-SEC-006.
    url_admin_twin_jwks: str = Field(default="", validation_alias="URL_ADMIN_TWIN_JWKS")

    # ── HTTP sidecar ──────────────────────────────────────────────────────────
    mcp_port: int = Field(default=7100, validation_alias="MCP_PORT")
    docs_enabled: bool = Field(default=False, validation_alias="DOCS_ENABLED")
    log_level: str = Field(default="INFO", validation_alias="MCP_SERVICE_LOG_LEVEL")

    # ── Backend de sessões (prefixo SESSION_) ─────────────────────────────────
    # O SessionStore é SQLite embarcado (hermético); as settings PostgreSQL abaixo
    # ficam prontas para o dual-write da Fase 2 (ver POSTGRES_INTEGRATION.md).
    pg_host: str = Field(default="claude-dev", description="PostgreSQL host")
    pg_port: int = Field(default=5432, description="PostgreSQL port")
    pg_db: str = Field(default="app", description="PostgreSQL database name")
    pg_user: str = Field(default="postgres", description="PostgreSQL user")
    pg_password: str = Field(default="postgres_password_local_dev", description="PostgreSQL password")
    pg_min_conn: int = Field(default=2, description="Minimum pool connections")
    pg_max_conn: int = Field(default=10, description="Maximum pool connections")

    # ── Convenções de sessão ──────────────────────────────────────────────────
    max_active_sessions: int = Field(default=50)
    default_list_limit: int = Field(default=20)
    default_base_branch: str = Field(
        default="develop",
        description="Branch base sugerida quando o agente cria a branch da sessão via deploy-mcp.",
    )

    @property
    def pg_dsn(self) -> str:
        """Return PostgreSQL connection string."""
        return (
            f"host={self.pg_host} port={self.pg_port} dbname={self.pg_db} "
            f"user={self.pg_user} password={self.pg_password}"
        )


# Alias de compatibilidade com o padrão canônico (architecture usa `Settings`).
Settings = SessionSettings


@lru_cache(maxsize=1)
def get_settings() -> SessionSettings:
    return SessionSettings()
