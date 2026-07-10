"""Settings do test-mcp (sidecar mcp_http, Model C).

Config de integração ao MCP Gateway central conforme:
  - docs/standards/STD-MCP-001-mcp-gateway-integration-contract.md
  - docs/standards/STD-SEC-006-token-model-c-inner-token.md

`test-mcp` é uma persona **DB-backed**: as tools persistem planos/cenários/
checklists/bugs num PostgreSQL via ``TestStore`` (psycopg2). O "backend" aqui é o
próprio banco (não há API REST HTTP a chamar), então NÃO há
``ServiceApiClient``/``MCP_SERVICE_BASE_URL``/``MCP_SERVICE_TOKEN`` — a config de
conexão (``TEST_PG_*``) permanece para a camada de store.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .secrets import load_secret

# namespace canônico = name_microservice ('platform-test-mcp') menos o prefixo
# 'platform-'. A audiência do inner token DEVE ser exatamente mcp:<namespace>.
NAMESPACE = "test-mcp"


class Settings(BaseSettings):
    # env_prefix='TEST_' aplica-se APENAS aos campos de DB (sem validation_alias);
    # os campos do gateway usam aliases canônicos SEM prefixo (MCP_TWIN_AUDIENCE, …).
    model_config = SettingsConfigDict(
        env_prefix="TEST_", env_file=".env", extra="ignore", case_sensitive=False
    )

    # ── Ambiente (STD-SEC-004: um único .env, discriminador RUNTIME_ENV) ───────
    # Não existem .env.dev/.hml/.prod nem ENV_PROFILE; o comportamento por ambiente
    # é gated por RUNTIME_ENV ∈ {local, cloud}. Alias SEM o prefixo TEST_.
    runtime_env: str = Field(default="local", validation_alias="RUNTIME_ENV")

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

    # ── PostgreSQL (camada de store) — env_prefix TEST_ ───────────────────────
    # STD-SEC-004: nenhum host/credencial hard-coded. host/senha default vazios →
    # exigidos via env (TEST_PG_HOST/TEST_PG_PASSWORD) ou Vault; obrigatórios em
    # cloud (enforce_security_invariants). A senha NUNCA fica no código.
    pg_host: str = Field(default="", description="PostgreSQL host")
    pg_port: int = Field(default=5432, description="PostgreSQL port")
    pg_db: str = Field(default="app", description="PostgreSQL database name")
    pg_user: str = Field(default="postgres", description="PostgreSQL user")
    pg_password: str = Field(default="", description="PostgreSQL password (via env/Vault)")
    pg_min_conn: int = Field(default=2, description="Minimum pool connections")
    pg_max_conn: int = Field(default=10, description="Maximum pool connections")

    # Test-specific settings
    default_list_limit: int = 20

    @field_validator("runtime_env")
    @classmethod
    def _validate_runtime_env(cls, v: str) -> str:
        v = (v or "local").strip().lower()
        if v not in ("local", "cloud"):
            raise ValueError("RUNTIME_ENV deve ser 'local' ou 'cloud'")
        return v

    @property
    def pg_password_resolved(self) -> str:
        """Senha do DB resolvida via Vault→env (STD-SEC-004). Nunca hard-coded.

        Vault (se `VAULT_ADDR`) → env `TEST_PG_PASSWORD` → o valor já carregado pelo
        pydantic (também de env) → "". Degradação graciosa: o boot nunca quebra.
        """
        return load_secret("test-mcp/pg-password", env_var="TEST_PG_PASSWORD", default=self.pg_password)

    @property
    def pg_dsn(self) -> str:
        """Return PostgreSQL connection string (senha resolvida via Vault→env)."""
        return (
            f"host={self.pg_host} port={self.pg_port} dbname={self.pg_db} "
            f"user={self.pg_user} password={self.pg_password_resolved}"
        )

    def enforce_security_invariants(self) -> None:
        """Fail-fast no boot (STD-SEC-001 / STD-SEC-004 / STD-SEC-006). Chamado em build_server().

        - Swagger/OpenAPI NUNCA exposto (DOCS_ENABLED=false em todo ambiente).
        - Audiência do inner token deve ser exatamente ``mcp:<namespace>``.
        - Em cloud, o JWKS do admin é obrigatório (sem ele o PEP não re-verifica).
        - Em cloud, a credencial do DB (senha) é obrigatória — nunca há default com
          senha no código; a resolução real passa por load_secret (Vault→env).
        """
        if self.docs_enabled:
            raise RuntimeError("INVARIANTE STD-SEC-001: DOCS_ENABLED deve ser false em todo ambiente")
        if not self.mcp_twin_audience.startswith("mcp:"):
            raise RuntimeError("INVARIANTE STD-SEC-006: MCP_TWIN_AUDIENCE deve ser 'mcp:<namespace>'")
        if self.runtime_env == "cloud" and not self.url_admin_twin_jwks:
            raise RuntimeError("INVARIANTE STD-SEC-006: URL_ADMIN_TWIN_JWKS é obrigatório em cloud")
        if self.runtime_env == "cloud" and not self.pg_password_resolved:
            raise RuntimeError(
                "INVARIANTE STD-SEC-004: senha do PostgreSQL (TEST_PG_PASSWORD/Vault) é obrigatória em cloud"
            )


# Alias de compatibilidade (a suíte histórica referencia ``TestSettings``).
TestSettings = Settings


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
