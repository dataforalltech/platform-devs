"""Settings do pipeline-mcp (sidecar mcp_http, Model C).

Config de integração ao MCP Gateway central conforme:
  - docs/standards/STD-MCP-001-mcp-gateway-integration-contract.md
  - docs/standards/STD-SEC-006-token-model-c-inner-token.md

`pipeline-mcp` é uma persona **stateful** (mantém estado de pipelines/gates/promoções
num PostgreSQL via `PipelineStore`) e fala com a **GitHub REST API** para criar/mergiar
PRs. Não há um Trinity backend HTTP intermediário, então NÃO há `ServiceApiClient`/
`MCP_SERVICE_BASE_URL`/`MCP_SERVICE_TOKEN` — a persistência é direta (psycopg2) e o
GitHub é chamado com `PIPELINE_GITHUB_TOKEN`/`PIPELINE_GITHUB_ORG`.

STD-SEC-004: um único `.env` (discriminador `RUNTIME_ENV`); NENHUM valor com cara de
credencial fica no código — host/senha do DB vêm de env (ou Vault via `load_secret`).
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_log = logging.getLogger(__name__)

# namespace canônico = name_microservice ('platform-pipeline-mcp') menos o
# prefixo 'platform-'. A audiência do inner token DEVE ser exatamente mcp:<namespace>.
NAMESPACE = "pipeline-mcp"


def load_secret(key: str, fallback: str = "") -> str:
    """Resolve um segredo via Vault (STD-SEC-004), degradando p/ env com graça.

    Só tenta o ``platform_crypto.VaultSecretsClient`` quando ``VAULT_ADDR`` está
    setado; o import é LAZY (dentro do try) para não acoplar o boot ao Vault. Em
    QUALQUER falha (Vault indisponível, import ausente, segredo vazio) degrada
    para o valor de env (``fallback``) — o boot NUNCA quebra por causa do Vault.
    Loga apenas a FONTE do segredo, nunca o valor (STD-OBS-001).
    """
    vault_addr = os.getenv("VAULT_ADDR", "").strip()
    if not vault_addr:
        _log.debug("secret_source key=%s source=env", key)
        return fallback
    try:
        from platform_crypto import VaultSecretsClient  # lazy: só quando há Vault

        value = VaultSecretsClient(vault_addr).get_secret(key)
        if value:
            _log.info("secret_source key=%s source=vault", key)
            return value
        _log.warning("secret_empty_from_vault key=%s source=env", key)
        return fallback
    except Exception as exc:  # noqa: BLE001 — Vault NUNCA derruba o boot (degrada p/ env)
        _log.warning("vault_unavailable key=%s source=env err=%s", key, type(exc).__name__)
        return fallback


class PipelineSettings(BaseSettings):
    """Settings do pipeline-mcp: gateway (Model C) + backend PostgreSQL."""

    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", case_sensitive=False, populate_by_name=True
    )

    # ── Ambiente (STD-SEC-004: um único .env, discriminador RUNTIME_ENV) ───────
    # Não existem .env.dev/.hml/.prod nem ENV_PROFILE; o comportamento por ambiente
    # é gated por RUNTIME_ENV ∈ {local, cloud}.
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

    # ── Backend PostgreSQL ────────────────────────────────────────────────────
    # STD-SEC-004: NENHUM valor com cara de credencial/host de ambiente fica no
    # código — host e senha vêm de env (ou Vault). Default vazio = exigido via env.
    pg_host: str = Field(default="", validation_alias="PG_HOST", description="PostgreSQL host")
    pg_port: int = Field(default=5432, validation_alias="PG_PORT", description="PostgreSQL port")
    pg_db: str = Field(default="pipeline_mcp", validation_alias="PG_DB", description="Database name")
    pg_user: str = Field(default="postgres", validation_alias="PG_USER", description="PostgreSQL user")
    pg_password: str = Field(
        default="", validation_alias="PG_PASSWORD", description="PostgreSQL password (env/Vault, sem default)"
    )
    pg_min_conn: int = Field(default=2, validation_alias="PG_MIN_CONN", description="Min pool connections")
    pg_max_conn: int = Field(default=10, validation_alias="PG_MAX_CONN", description="Max pool connections")

    # ── GitHub (criação/merge de PRs durante promoções) ───────────────────────
    github_token: str = Field(default="", validation_alias="PIPELINE_GITHUB_TOKEN")
    github_org: str = Field(default="", validation_alias="PIPELINE_GITHUB_ORG")

    @field_validator("runtime_env")
    @classmethod
    def _validate_runtime_env(cls, v: str) -> str:
        v = (v or "local").strip().lower()
        if v not in ("local", "cloud"):
            raise ValueError("RUNTIME_ENV deve ser 'local' ou 'cloud'")
        return v

    @model_validator(mode="after")
    def _resolve_secrets(self) -> PipelineSettings:
        """Resolve a senha do DB via Vault-fallback (env se Vault ausente)."""
        self.pg_password = load_secret(f"{NAMESPACE}/pg_password", self.pg_password)
        return self

    @property
    def pg_dsn(self) -> str:
        """String de conexão libpq (keyword form) para o psycopg2 pool."""
        return (
            f"host={self.pg_host} port={self.pg_port} dbname={self.pg_db} "
            f"user={self.pg_user} password={self.pg_password}"
        )

    def enforce_security_invariants(self) -> None:
        """Fail-fast no boot (STD-SEC-001 / STD-SEC-004 / STD-SEC-006).

        Chamado em build_server():
        - Swagger/OpenAPI NUNCA exposto (DOCS_ENABLED=false em todo ambiente).
        - Audiência do inner token deve ser exatamente ``mcp:<namespace>``.
        - Em cloud, o JWKS do admin é obrigatório (sem ele o PEP não re-verifica)
          e a senha do DB DEVE vir de env/Vault (nunca de default no código).
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
                    "INVARIANTE STD-SEC-004: PG_PASSWORD é obrigatório em cloud "
                    "(sem default no código; via env ou Vault)"
                )


# Alias de compatibilidade com o padrão do template (Settings).
Settings = PipelineSettings


@lru_cache(maxsize=1)
def get_settings() -> PipelineSettings:
    return PipelineSettings()
