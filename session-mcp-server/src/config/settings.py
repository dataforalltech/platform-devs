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

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .secrets import load_secret

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

    # ── Ambiente (STD-SEC-004: um único .env, discriminador RUNTIME_ENV) ───────
    # Não existem .env.dev/.hml/.prod nem ENV_PROFILE; o comportamento por ambiente
    # é gated por RUNTIME_ENV ∈ {local, cloud}. validation_alias ignora env_prefix.
    runtime_env: str = Field(default="local", validation_alias="RUNTIME_ENV")

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
    # ficam prontas para o dual-write da Fase 2. STD-SEC-004: NENHUM default com cara
    # de credencial no código — host/senha vêm do ambiente (ou do Vault via
    # ``load_secret``); a senha nunca tem valor real hardcoded.
    pg_host: str = Field(default="", description="PostgreSQL host (env: SESSION_PG_HOST)")
    pg_port: int = Field(default=5432, description="PostgreSQL port")
    pg_db: str = Field(default="app", description="PostgreSQL database name")
    pg_user: str = Field(default="postgres", description="PostgreSQL user")
    # Senha resolvida por load_secret: Vault (se VAULT_ADDR) → env → "" (fail-closed).
    pg_password: str = Field(
        default_factory=lambda: load_secret(
            f"{NAMESPACE}/pg_password", env_var="SESSION_PG_PASSWORD", default=""
        ),
        description="PostgreSQL password (Vault/env — sem default no código)",
    )
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

    @field_validator("runtime_env")
    @classmethod
    def _validate_runtime_env(cls, v: str) -> str:
        v = (v or "local").strip().lower()
        if v not in ("local", "cloud"):
            raise ValueError("RUNTIME_ENV deve ser 'local' ou 'cloud'")
        return v

    def enforce_security_invariants(self) -> None:
        """Fail-fast no boot (STD-SEC-001 / STD-SEC-004 / STD-SEC-006). Chamado em build_server().

        - Swagger/OpenAPI NUNCA exposto (DOCS_ENABLED=false em todo ambiente).
        - Audiência do inner token deve ser exatamente ``mcp:<namespace>``.
        - Em cloud, o JWKS do admin é obrigatório (sem ele o PEP não re-verifica).
        - Em cloud, a credencial do backend (senha do Postgres) é obrigatória — nunca
          um default hardcoded (STD-SEC-004); deve vir do Vault/env via ``load_secret``.
        """
        if self.docs_enabled:
            raise RuntimeError("INVARIANTE STD-SEC-001: DOCS_ENABLED deve ser false em todo ambiente")
        if not self.mcp_twin_audience.startswith("mcp:"):
            raise RuntimeError("INVARIANTE STD-SEC-006: MCP_TWIN_AUDIENCE deve ser 'mcp:<namespace>'")
        if self.runtime_env == "cloud":
            if not self.url_admin_twin_jwks:
                raise RuntimeError("INVARIANTE STD-SEC-006: URL_ADMIN_TWIN_JWKS é obrigatório em cloud")
            if not self.pg_password:
                raise RuntimeError(
                    "INVARIANTE STD-SEC-004: credencial do backend (SESSION_PG_PASSWORD "
                    "ou Vault) é obrigatória em cloud — nunca use default hardcoded"
                )


# Alias de compatibilidade com o padrão canônico (architecture usa `Settings`).
Settings = SessionSettings


@lru_cache(maxsize=1)
def get_settings() -> SessionSettings:
    return SessionSettings()
