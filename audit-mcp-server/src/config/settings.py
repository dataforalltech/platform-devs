"""Settings do audit-mcp (sidecar mcp_http, Model C).

Config de integração ao MCP Gateway central conforme:
  - docs/standards/STD-MCP-001-mcp-gateway-integration-contract.md
  - docs/standards/STD-SEC-006-token-model-c-inner-token.md

`audit-mcp` NÃO é compute-only: persiste auditorias/aprovações num backend
PostgreSQL (``AuditStore``). Por isso mantém as settings de conexão (prefixo
``AUDIT_``) e injeta o store no dispatcher. As settings do gateway (audiência do
inner token, JWKS do platform-admin, porta do sidecar) usam ``validation_alias``
próprio — o prefixo ``AUDIT_`` NÃO se aplica a campos com alias.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# namespace canônico = name_microservice ('platform-audit-mcp') menos o prefixo
# 'platform-'. A audiência do inner token DEVE ser exatamente mcp:<namespace>.
NAMESPACE = "audit-mcp"


class AuditSettings(BaseSettings):
    """Settings do audit-mcp: gateway (Model C) + backend PostgreSQL."""

    model_config = SettingsConfigDict(
        env_prefix="AUDIT_",
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

    # ── Backend PostgreSQL (prefixo AUDIT_) ───────────────────────────────────
    pg_host: str = Field(default="claude-dev", description="PostgreSQL host")
    pg_port: int = Field(default=5432, description="PostgreSQL port")
    pg_db: str = Field(default="app", description="PostgreSQL database name")
    pg_user: str = Field(default="postgres", description="PostgreSQL user")
    pg_password: str = Field(default="postgres_password_local_dev", description="PostgreSQL password")
    pg_min_conn: int = Field(default=2, description="Minimum pool connections")
    pg_max_conn: int = Field(default=10, description="Maximum pool connections")

    # Legacy SQLite path (compat durante migração)
    db_path: str = ".audit.db"

    # ── Auditoria (checkers / policies) ───────────────────────────────────────
    github_token: str = ""
    github_org: str = "dataforalltech"
    policies_path: str = str(Path(__file__).parent.parent / "policies")

    @property
    def pg_dsn(self) -> str:
        """Return PostgreSQL connection string."""
        return (
            f"host={self.pg_host} port={self.pg_port} dbname={self.pg_db} "
            f"user={self.pg_user} password={self.pg_password}"
        )


# Alias de compatibilidade com o padrão canônico (architecture usa `Settings`).
Settings = AuditSettings


@lru_cache(maxsize=1)
def get_settings() -> AuditSettings:
    return AuditSettings()
