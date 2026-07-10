"""Settings do qa-mcp (sidecar mcp_http, Model C).

Config de integração ao MCP Gateway central conforme:
  - docs/standards/STD-MCP-001-mcp-gateway-integration-contract.md
  - docs/standards/STD-SEC-006-token-model-c-inner-token.md

`qa-mcp` executa testes/análises e PERSISTE runs num store PostgreSQL local
(src/db/store.py) — não fala com um backend REST (não há `ServiceApiClient`/
`MCP_SERVICE_BASE_URL`). Os campos QA_* originais (db_path, screenshots_dir, …)
são preservados; acrescentam-se os campos canônicos do Model C.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

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

    # ── Backend PostgreSQL (STD-SEC-004: credencial só via env/Vault) ─────────
    # DSN do store (src/db/store.py). NUNCA um valor com senha embutida no código;
    # default vazio → resolvido em runtime via load_secret (Vault→env). Obrigatório
    # em cloud (enforce_security_invariants). Alias SEM o prefixo QA_.
    pg_dsn: str = Field(default="", validation_alias="PG_DSN")

    # ── HTTP sidecar ──────────────────────────────────────────────────────────
    mcp_port: int = Field(default=7100, validation_alias="MCP_PORT")
    docs_enabled: bool = Field(default=False, validation_alias="DOCS_ENABLED")
    log_level: str = Field(default="INFO", validation_alias="MCP_SERVICE_LOG_LEVEL")

    # ── QA-específico (preservado) ────────────────────────────────────────────
    db_path: str = str(Path.home() / ".qa-mcp" / "runs.db")
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

    def enforce_security_invariants(self) -> None:
        """Fail-fast no boot (STD-SEC-001 / STD-SEC-004 / STD-SEC-006). Chamado em build_server().

        - Swagger/OpenAPI NUNCA exposto (DOCS_ENABLED=false em todo ambiente).
        - Audiência do inner token deve ser exatamente ``mcp:<namespace>``.
        - Em cloud, o JWKS do admin é obrigatório (sem ele o PEP não re-verifica).
        - Em cloud, a credencial do DB (PG_DSN) é obrigatória — nunca há default
          com senha no código; a resolução real passa por load_secret (Vault→env).
        """
        if self.docs_enabled:
            raise RuntimeError("INVARIANTE STD-SEC-001: DOCS_ENABLED deve ser false em todo ambiente")
        if not self.mcp_twin_audience.startswith("mcp:"):
            raise RuntimeError("INVARIANTE STD-SEC-006: MCP_TWIN_AUDIENCE deve ser 'mcp:<namespace>'")
        if self.runtime_env == "cloud" and not self.url_admin_twin_jwks:
            raise RuntimeError("INVARIANTE STD-SEC-006: URL_ADMIN_TWIN_JWKS é obrigatório em cloud")
        if self.runtime_env == "cloud" and not self.pg_dsn:
            raise RuntimeError("INVARIANTE STD-SEC-004: PG_DSN (credencial do DB) é obrigatório em cloud")


# Alias de compatibilidade com o padrão canônico (architecture usa `Settings`).
Settings = QASettings


@lru_cache(maxsize=1)
def get_settings() -> QASettings:
    return QASettings()
