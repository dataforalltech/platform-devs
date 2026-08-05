"""Settings do qa-mcp (sidecar mcp_http, Model C).

Config de integração ao MCP Gateway central conforme:
  - docs/standards/STD-MCP-001-mcp-gateway-integration-contract.md
  - docs/standards/STD-SEC-006-token-model-c-inner-token.md

`qa-mcp` executa testes/análises e PERSISTE runs num log append-only. A persistência
roda 100% sobre o ORM canônico (`platform_database.orm`), **tenant-scoped e dual-db**:
credencial-zero (ORM-H-12) — o serviço só conhece o `tenant_id`; a credencial do banco
do tenant vem de `ADMIN_DATAFORALL.PLATFORMS` (resolvida pela lib). Estas Settings expõem
os protocolos `DBSettings` (`DB_*`, fallback compartilhado) e `AdminDBSettings`
(`ADMIN_DB_*`, conexão admin que lê PLATFORMS) — o mesmo objeto é passado a
`orm.configure()` no boot. Os campos QA_* originais (screenshots_dir, thresholds, …) são
preservados.

STD-SEC-004: um único `.env` (discriminador `RUNTIME_ENV`); NENHUM valor com cara de
credencial fica no código — host/senha do DB/admin vêm de env (ou Vault via `load_secret`).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .secrets import load_secret

# namespace canônico = name_microservice ('platform-qa-mcp') menos o prefixo
# 'platform-'. A audiência do inner token DEVE ser exatamente mcp:<namespace>.
NAMESPACE = "qa-mcp"


class QASettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="QA_",
        env_file=".env",
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,
    )

    # ── Ambiente (STD-SEC-004: um único .env, discriminador RUNTIME_ENV) ───────
    # Não existem .env.dev/.hml/.prod nem ENV_PROFILE; o comportamento por ambiente
    # é gated por RUNTIME_ENV ∈ {local, cloud}. Alias SEM o prefixo QA_.
    runtime_env: str = Field(default="local", validation_alias="RUNTIME_ENV")

    # ── Integração com o gateway (STD-MCP-001 / STD-SEC-006) ──────────────────
    # Audiência exata que o PEP re-verifica no inner token (a falha de integração
    # nº 1 é audiência divergente → 401). Aliases SEM o prefixo QA_.
    mcp_twin_audience: str = Field(default=f"mcp:{NAMESPACE}", validation_alias="MCP_TWIN_AUDIENCE")
    # JWKS do platform-admin (emissor do twin/inner token) — mesma de STD-SEC-006.
    url_admin_twin_jwks: str = Field(default="", validation_alias="URL_ADMIN_TWIN_JWKS")

    # ── Backend do tenant (DBSettings — ORM canônico, dual-db) ────────────────
    # Fallback compartilhado (shared-admin credential model): a credencial real do
    # tenant vem de ADMIN_DATAFORALL.PLATFORMS; estes DB_* são o fallback quando a
    # PLATFORMS row não traz o campo. DB_ENGINE decide o dialeto (mysql/postgresql).
    # STD-SEC-004: nenhum valor com cara de credencial fica no código (env/Vault).
    # Aliases SEM o prefixo QA_ (protocolo canônico do ORM).
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

    # ── HTTP sidecar ──────────────────────────────────────────────────────────
    mcp_port: int = Field(default=7100, validation_alias="MCP_PORT")
    docs_enabled: bool = Field(default=False, validation_alias="DOCS_ENABLED")
    log_level: str = Field(default="INFO", validation_alias="MCP_SERVICE_LOG_LEVEL")

    # ── QA-específico (preservado; lido com o prefixo QA_) ────────────────────
    screenshots_dir: str = str(Path.home() / ".qa-mcp" / "screenshots")
    baselines_dir: str = str(Path.home() / ".qa-mcp" / "baselines")

    http_timeout: float = 10.0
    browser_timeout: int = 30_000  # ms para Playwright
    subprocess_timeout: int = 120  # segundos para processos externos

    default_browser: str = "chromium"  # chromium | firefox | webkit
    headless: bool = True

    complexity_threshold: int = 10  # CC > 10 é "complexo"
    coverage_threshold: float = 80.0  # % mínimo de cobertura

    @field_validator("runtime_env")
    @classmethod
    def _validate_runtime_env(cls, v: str) -> str:
        v = (v or "local").strip().lower()
        if v not in ("local", "cloud"):
            raise ValueError("RUNTIME_ENV deve ser 'local' ou 'cloud'")
        return v

    @model_validator(mode="after")
    def _resolve_secrets(self) -> QASettings:
        """Resolve as senhas (tenant + admin) pelo bootstrap do STD-SEC-004.

        O espaço do serviço no Vault agora é o ``service=`` do cliente, então o
        nome da chave é só ``db_password`` — prefixá-lo com o namespace montava
        ``dataforall/<ns>/<ns>/db_password``, um path que ninguém provisiona.
        Em cloud, Vault fora do ar recusa o boot em vez de degradar para env.
        """
        self.DB_PASSWORD = load_secret(
            "db_password",
            env_var="DB_PASSWORD",
            default=self.DB_PASSWORD,
            runtime_env=self.runtime_env,
        )
        self.ADMIN_DB_PASSWORD = load_secret(
            "admin_db_password",
            env_var="ADMIN_DB_PASSWORD",
            default=self.ADMIN_DB_PASSWORD,
            runtime_env=self.runtime_env,
        )
        return self

    def enforce_security_invariants(self) -> None:
        """Fail-fast no boot (STD-SEC-001 / STD-SEC-004 / STD-SEC-006). Chamado em build_server().

        - Swagger/OpenAPI NUNCA exposto (DOCS_ENABLED=false em todo ambiente).
        - Audiência do inner token deve ser exatamente ``mcp:<namespace>``.
        - Em cloud, o JWKS do admin é obrigatório (sem ele o PEP não re-verifica) e a
          conexão admin (host + senha p/ resolver o tenant via PLATFORMS) DEVE vir de
          env/Vault (nunca de default no código).
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


# Alias de compatibilidade com o padrão canônico (architecture usa `Settings`).
Settings = QASettings


@lru_cache(maxsize=1)
def get_settings() -> QASettings:
    return QASettings()
