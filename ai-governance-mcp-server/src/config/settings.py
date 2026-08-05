"""Settings do ai-governance-mcp (sidecar mcp_http, Model C).

Config de integração ao MCP Gateway central conforme:
  - docs/standards/STD-MCP-001-mcp-gateway-integration-contract.md
  - docs/standards/STD-SEC-006-token-model-c-inner-token.md

`ai-governance-mcp` é **híbrido**: a maior parte das tools é compute-only sobre a
knowledge-base local (Markdown/YAML read-only, git-trackeada — `kb_path`), mas os DOIS
stores mutáveis (mural cross-repo de sugestões + trilha de auditoria de decisões) rodam
sobre o ORM canônico (`platform_database.orm`), **tenant-scoped e dual-db**:
credencial-zero (ORM-H-12) — o serviço só conhece o `tenant_id`; a credencial do banco
do tenant vem de `ADMIN_DATAFORALL.PLATFORMS` (resolvida pela lib). Estas Settings
expõem os protocolos `DBSettings` (`DB_*`, fallback compartilhado) e `AdminDBSettings`
(`ADMIN_DB_*`, conexão admin que lê PLATFORMS) — o mesmo objeto é passado a
`orm.configure()` no boot.

STD-SEC-004: um único `.env` (discriminador `RUNTIME_ENV`); NENHUM valor com cara de
credencial fica no código — host/senha do DB/admin vêm de env (ou Vault via `load_secret`).
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_log = logging.getLogger(__name__)

# namespace canônico = name_microservice ('platform-ai-governance-mcp') menos o
# prefixo 'platform-'. A audiência do inner token DEVE ser exatamente mcp:<namespace>.
NAMESPACE = "ai-governance-mcp"

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_KB_PATH = _PROJECT_ROOT / "knowledge-base"


class SecretResolutionError(RuntimeError):
    """Segredo obrigatório não pôde ser resolvido pela fonte aprovada."""


def load_secret(
    name: str,
    fallback: str = "",
    *,
    runtime_env: str = "local",
    required: bool = False,
) -> str:
    """Resolve um segredo pelo bootstrap de segredos do STD-SEC-004.

    Em ``cloud`` a fonte é o Vault e **só** o Vault: qualquer falha de auth/fetch
    levanta ``SecretResolutionError`` e o serviço não sobe — "a ausência ou
    invalidez de uma credencial exigida MUST falhar fechada" (STD-SEC-002, §MUST).
    O ``fallback`` de env/.env é deliberadamente ignorado em cloud, senão o
    bootstrap degrada em silêncio para uma fonte que o standard não admite ali.

    Em ``local`` o Vault é opcional — só é consultado quando ``VAULT_ADDR`` está
    setado — e qualquer falha degrada para o valor de env, que é o "fallback local
    controlado" que o STD-SEC-004 permite.

    ``required`` decide o que fazer com valor AUSENTE (Vault vazio e sem fallback
    utilizável); falha de comunicação em cloud levanta independentemente dele.

    Loga apenas o nome lógico e a FONTE do segredo, nunca o valor (STD-OBS-001).
    """
    is_cloud = runtime_env == "cloud"
    if not is_cloud and not os.getenv("VAULT_ADDR", "").strip():
        _log.debug("secret_source name=%s source=env", name)
        if required and not fallback:
            raise SecretResolutionError(
                f"segredo obrigatório '{name}' ausente no runtime local"
            )
        return fallback
    try:
        from platform_crypto import VaultSecretsClient  # lazy: import opcional

        # `service` é o espaço de segredos do serviço (path dataforall/<service>/<name>);
        # `name` é a chave lógica dentro dele. Passar o endereço do Vault aqui — como
        # fazia a versão anterior — monta um path que ninguém provisionou.
        value = VaultSecretsClient(service=NAMESPACE).get(name)
    except Exception as exc:  # noqa: BLE001 — fronteira de bootstrap, mensagem sanitizada
        if is_cloud:
            raise SecretResolutionError(
                f"segredo obrigatório '{name}' não pôde ser resolvido do Vault "
                f"({type(exc).__name__})"
            ) from exc
        _log.warning(
            "vault_unavailable name=%s source=env err=%s", name, type(exc).__name__
        )
        if required and not fallback:
            raise SecretResolutionError(
                f"segredo obrigatório '{name}' indisponível"
            ) from exc
        return fallback
    if value:
        _log.info("secret_source name=%s source=vault service=%s", name, NAMESPACE)
        return value
    if is_cloud and required:
        raise SecretResolutionError(f"segredo obrigatório '{name}' vazio no Vault")
    if is_cloud:
        _log.warning("secret_empty_from_vault name=%s source=absent", name)
        return ""
    _log.warning("secret_empty_from_vault name=%s source=env", name)
    if required and not fallback:
        raise SecretResolutionError(f"segredo obrigatório '{name}' ausente")
    return fallback


class Settings(BaseSettings):
    """Configuração do servidor MCP: gateway (Model C) + backend ORM dual-db."""

    model_config = SettingsConfigDict(
        env_prefix="GOVERNANCE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,
    )

    # ── Ambiente (STD-SEC-004: um único .env, discriminador RUNTIME_ENV) ───────
    # Não existem .env.dev/.hml/.prod nem ENV_PROFILE; o comportamento por ambiente
    # é gated por RUNTIME_ENV ∈ {local, cloud}. validation_alias absoluto (sem o
    # prefixo GOVERNANCE_) para casar com o contrato compartilhado dos sidecars.
    runtime_env: str = Field(default="local", validation_alias="RUNTIME_ENV")

    # ── Integração com o gateway (STD-MCP-001 / STD-SEC-006) ──────────────────
    # Audiência exata que o PEP re-verifica no inner token (a falha de integração
    # nº 1 é audiência divergente → 401). validation_alias absoluto (sem prefixo
    # GOVERNANCE_) para casar com o contrato do gateway.
    mcp_twin_audience: str = Field(default=f"mcp:{NAMESPACE}", validation_alias="MCP_TWIN_AUDIENCE")
    # JWKS do platform-admin (emissor do twin/inner token) — mesma de STD-SEC-006.
    url_admin_twin_jwks: str = Field(default="", validation_alias="URL_ADMIN_TWIN_JWKS")
    # HTTP sidecar (bind interno; ingress só via gateway, INV-1).
    mcp_port: int = Field(default=7100, validation_alias="MCP_PORT")
    docs_enabled: bool = Field(default=False, validation_alias="DOCS_ENABLED")

    # ── Backend do tenant (DBSettings — ORM canônico, dual-db) ────────────────
    # Fallback compartilhado (shared-admin credential model): a credencial real do
    # tenant vem de ADMIN_DATAFORALL.PLATFORMS; estes DB_* são o fallback quando a
    # PLATFORMS row não traz o campo. DB_ENGINE decide o dialeto (mysql/postgresql).
    # STD-SEC-004: nenhum valor com cara de credencial fica no código (env/Vault).
    DB_ENGINE: str = Field(default="mysql", validation_alias="DB_ENGINE")
    DB_HOST: str = Field(default="", validation_alias="DB_HOST")
    DB_PORT: int = Field(default=3306, validation_alias="DB_PORT")
    DB_NAME: str = Field(default="", validation_alias="DB_NAME")
    DB_USER: str = Field(default="root", validation_alias="DB_USER")
    DB_PASSWORD: str = Field(default="", validation_alias="DB_PASSWORD")
    DB_POOL_MIN_SIZE: int = Field(default=1, validation_alias="DB_POOL_MIN_SIZE")
    DB_POOL_MAX_SIZE: int = Field(default=10, validation_alias="DB_POOL_MAX_SIZE")
    DB_POOL_ACQUIRE_TIMEOUT_SECONDS: float = Field(
        default=30.0, validation_alias="DB_POOL_ACQUIRE_TIMEOUT_SECONDS"
    )
    DB_POOL_RECYCLE_SECONDS: int = Field(default=1800, validation_alias="DB_POOL_RECYCLE_SECONDS")
    DB_QUERY_TIMEOUT_SECONDS: int = Field(default=60, validation_alias="DB_QUERY_TIMEOUT_SECONDS")
    DB_HEALTH_POOL_SIZE: int = Field(default=1, validation_alias="DB_HEALTH_POOL_SIZE")
    DB_SSLMODE: str | None = Field(default=None, validation_alias="DB_SSLMODE")

    # ── Conexão admin (AdminDBSettings — lê ADMIN_DATAFORALL.PLATFORMS) ────────
    # Resolve o tenant -> credencial do seu banco. É a fonte passada a
    # orm.configure()/get_pool_for_tenant(). O db name é fixo "ADMIN_DATAFORALL".
    ADMIN_DB_HOST: str = Field(default="", validation_alias="ADMIN_DB_HOST")
    ADMIN_DB_PORT: int = Field(default=3306, validation_alias="ADMIN_DB_PORT")
    ADMIN_DB_USER: str = Field(default="root", validation_alias="ADMIN_DB_USER")
    ADMIN_DB_PASSWORD: str = Field(default="", validation_alias="ADMIN_DB_PASSWORD")

    # ── Knowledge base / governança (compute-only; read-only, git-trackeada) ──
    kb_path: Path = Field(
        default=_DEFAULT_KB_PATH,
        description="Pasta com os arquivos Markdown/YAML da base de conhecimento (read-only).",
    )
    log_level: str = Field(default="INFO", validation_alias="MCP_SERVICE_LOG_LEVEL")
    log_format: str = Field(default="json", description="json | text")
    search_max_limit: int = Field(default=20, ge=1, le=100)
    search_default_limit: int = Field(default=5, ge=1, le=50)
    search_snippet_length: int = Field(default=400, ge=80, le=4000)

    @field_validator("runtime_env")
    @classmethod
    def _validate_runtime_env(cls, v: str) -> str:
        v = (v or "local").strip().lower()
        if v not in ("local", "cloud"):
            raise ValueError("RUNTIME_ENV deve ser 'local' ou 'cloud'")
        return v

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR"}
        upper = v.upper()
        if upper not in allowed:
            raise ValueError(f"log_level deve ser um de {sorted(allowed)}")
        return upper

    @field_validator("log_format")
    @classmethod
    def _validate_log_format(cls, v: str) -> str:
        allowed = {"json", "text"}
        lower = v.lower()
        if lower not in allowed:
            raise ValueError(f"log_format deve ser um de {sorted(allowed)}")
        return lower

    @field_validator("kb_path")
    @classmethod
    def _resolve_kb_path(cls, v: Path) -> Path:
        return v.expanduser().resolve()

    @model_validator(mode="after")
    def _resolve_secrets(self) -> Settings:
        """Resolve as senhas (tenant + admin) via Vault-fallback (env se Vault ausente)."""
        self.DB_PASSWORD = load_secret("db_password", self.DB_PASSWORD, runtime_env=self.runtime_env)
        self.ADMIN_DB_PASSWORD = load_secret("admin_db_password", self.ADMIN_DB_PASSWORD, runtime_env=self.runtime_env)
        return self

    def enforce_security_invariants(self) -> None:
        """Fail-fast no boot (STD-SEC-001 / STD-SEC-004 / STD-SEC-006).

        Chamado em build_server():
        - Swagger/OpenAPI NUNCA exposto (DOCS_ENABLED=false em todo ambiente).
        - Audiência do inner token deve ser exatamente ``mcp:<namespace>``.
        - Em cloud, o JWKS do admin é obrigatório (sem ele o PEP não re-verifica) e a
          conexão admin (host + senha p/ resolver o tenant via PLATFORMS) DEVE vir de
          env/Vault (nunca de default no código) — os stores mutáveis são credencial-zero.
        """
        if self.docs_enabled:
            raise RuntimeError("INVARIANTE STD-SEC-001: DOCS_ENABLED deve ser false em todo ambiente")
        if not self.mcp_twin_audience.startswith("mcp:"):
            raise RuntimeError("INVARIANTE STD-SEC-006: MCP_TWIN_AUDIENCE deve ser 'mcp:<namespace>'")
        if self.runtime_env == "cloud":
            if not self.url_admin_twin_jwks:
                raise RuntimeError("INVARIANTE STD-SEC-006: URL_ADMIN_TWIN_JWKS é obrigatório em cloud")
            if not self.ADMIN_DB_HOST or not self.ADMIN_DB_PASSWORD:
                raise RuntimeError(
                    "INVARIANTE STD-SEC-004: ADMIN_DB_HOST/ADMIN_DB_PASSWORD são obrigatórios em "
                    "cloud (resolução credencial-zero do tenant via PLATFORMS; sem default no código)"
                )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Retorna instância singleton de Settings."""
    return Settings()
