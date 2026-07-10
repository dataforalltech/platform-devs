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

import logging
import os
from functools import lru_cache

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_log = logging.getLogger(__name__)

# namespace canônico = name_microservice ('platform-docs-mcp') menos o prefixo
# 'platform-'. A audiência do inner token DEVE ser exatamente mcp:<namespace>.
NAMESPACE = "docs-mcp"


def load_secret(key: str, fallback: str = "") -> str:
    """Resolve um segredo via Vault (STD-SEC-004), degradando p/ env com graça.

    Só tenta o ``platform_crypto.VaultSecretsClient`` quando ``VAULT_ADDR`` está
    setado; o import é LAZY (dentro do try) para não acoplar o boot ao Vault. Em
    QUALQUER falha (Vault indisponível, import ausente, segredo vazio) degrada
    para o valor de env (``fallback``) — o boot NUNCA quebra por causa do Vault.
    Loga apenas a FONTE do segredo, nunca o valor.
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


class Settings(BaseSettings):
    # env_prefix DOCS_ preserva os nomes das envs de banco (DOCS_PG_*); os campos
    # do gateway usam validation_alias absoluto (bypassa o prefixo).
    model_config = SettingsConfigDict(
        env_prefix="DOCS_", env_file=".env", extra="ignore", case_sensitive=False
    )

    # ── Ambiente (STD-SEC-004: um único .env, discriminador RUNTIME_ENV) ───────
    # Não existem .env.dev/.hml/.prod nem ENV_PROFILE; o comportamento por ambiente
    # é gated por RUNTIME_ENV ∈ {local, cloud}. validation_alias ignora env_prefix.
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

    # ── PostgreSQL (store de índice + histórico de auditoria) ─────────────────
    # STD-SEC-004: NENHUM valor com cara de credencial/host de ambiente fica no
    # código — host e senha vêm de env (ou Vault). Default vazio = exigido via env.
    pg_host: str = Field(default="", description="PostgreSQL host")
    pg_port: int = Field(default=5432, description="PostgreSQL port")
    pg_db: str = Field(default="app", description="PostgreSQL database name")
    pg_user: str = Field(default="postgres", description="PostgreSQL user")
    pg_password: str = Field(default="", description="PostgreSQL password (env/Vault, sem default)")
    pg_min_conn: int = Field(default=2, description="Minimum pool connections")
    pg_max_conn: int = Field(default=10, description="Maximum pool connections")

    # ── Docs-specific ─────────────────────────────────────────────────────────
    http_timeout: float = 10.0  # para check_links externo
    stale_days_threshold: int = 90  # docs sem update em X dias = stale
    check_external_links: bool = False  # httpx em links externos (lento)
    max_file_size_kb: int = 500  # ignora arquivos maiores que X KB no scan
    coverage_threshold: float = 80.0  # % mínimo de docs para score máximo

    @field_validator("runtime_env")
    @classmethod
    def _validate_runtime_env(cls, v: str) -> str:
        v = (v or "local").strip().lower()
        if v not in ("local", "cloud"):
            raise ValueError("RUNTIME_ENV deve ser 'local' ou 'cloud'")
        return v

    @model_validator(mode="after")
    def _resolve_secrets(self) -> Settings:
        """Resolve a senha do DB via Vault-fallback (env se Vault ausente)."""
        self.pg_password = load_secret(f"{NAMESPACE}/pg_password", self.pg_password)
        return self

    @property
    def pg_dsn(self) -> str:
        """Return PostgreSQL connection string."""
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
                    "INVARIANTE STD-SEC-004: DOCS_PG_PASSWORD é obrigatório em cloud "
                    "(sem default no código; via env ou Vault)"
                )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


# Backward-compat: o store e as tools ainda tipam `DocsSettings`.
DocsSettings = Settings
