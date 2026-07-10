"""Settings do ai-governance-mcp (sidecar mcp_http, Model C).

Config de integração ao MCP Gateway central conforme:
  - docs/standards/STD-MCP-001-mcp-gateway-integration-contract.md
  - docs/standards/STD-SEC-006-token-model-c-inner-token.md

`ai-governance-mcp` é uma persona **compute-only**: gera diretrizes/políticas/validações
a partir da knowledge-base local (não há Trinity backend/REST a chamar), então NÃO há
`ServiceApiClient`/`MCP_SERVICE_BASE_URL`/`MCP_SERVICE_TOKEN` aqui. Os campos de
knowledge-base (kb_path, suggestions_path, audit_path) continuam presentes — são a
fonte de dados do serviço.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# namespace canônico = name_microservice ('platform-ai-governance-mcp') menos o
# prefixo 'platform-'. A audiência do inner token DEVE ser exatamente mcp:<namespace>.
NAMESPACE = "ai-governance-mcp"

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_KB_PATH = _PROJECT_ROOT / "knowledge-base"


class Settings(BaseSettings):
    """Configuração do servidor MCP. Todos os valores têm default seguro."""

    model_config = SettingsConfigDict(
        env_prefix="GOVERNANCE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
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

    # ── Knowledge base / governança (compute-only; sem backend REST) ──────────
    kb_path: Path = Field(
        default=_DEFAULT_KB_PATH,
        description="Pasta com os arquivos Markdown da base de conhecimento.",
    )
    suggestions_path: Path | None = Field(
        default=None,
        description=(
            "Pasta de persistência das sugestões cross-repo. Default: "
            "<kb_path>/suggestions/. Pode ser sobrescrita via "
            "GOVERNANCE_SUGGESTIONS_PATH para isolar de KB git-trackeada."
        ),
    )
    audit_path: Path | None = Field(
        default=None,
        description=(
            "Caminho do arquivo JSONL de auditoria de decisões. Default: "
            "<kb_path>/audit/decisions.jsonl. Pode ser sobrescrito via "
            "GOVERNANCE_AUDIT_PATH para armazenar fora da KB git-trackeada."
        ),
    )
    log_level: str = Field(default="INFO", description="DEBUG | INFO | WARNING | ERROR")
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

    @field_validator("suggestions_path")
    @classmethod
    def _resolve_suggestions_path(cls, v: Path | None) -> Path | None:
        return v.expanduser().resolve() if v is not None else None

    @field_validator("audit_path")
    @classmethod
    def _resolve_audit_path(cls, v: Path | None) -> Path | None:
        return v.expanduser().resolve() if v is not None else None

    @property
    def effective_suggestions_path(self) -> Path:
        """Resolve o path final, com fallback para <kb_path>/suggestions/."""
        if self.suggestions_path is not None:
            return self.suggestions_path
        return self.kb_path / "suggestions"

    @property
    def effective_audit_path(self) -> Path:
        """Resolve o path final do arquivo de auditoria."""
        if self.audit_path is not None:
            return self.audit_path
        return self.kb_path / "audit" / "decisions.jsonl"

    def enforce_security_invariants(self) -> None:
        """Fail-fast no boot (STD-SEC-001 / STD-SEC-006). Chamado em build_server().

        - Swagger/OpenAPI NUNCA exposto (DOCS_ENABLED=false em todo ambiente).
        - Audiência do inner token deve ser exatamente ``mcp:<namespace>``.
        - Em cloud, o JWKS do admin é obrigatório (sem ele o PEP não re-verifica).

        ai-governance-mcp é compute-only sobre a knowledge-base em filesystem — não há
        backend/credencial de DB a exigir (STD-SEC-004 é satisfeito por ausência de
        segredo no código; os únicos campos de storage são paths, não credenciais).
        """
        if self.docs_enabled:
            raise RuntimeError("INVARIANTE STD-SEC-001: DOCS_ENABLED deve ser false em todo ambiente")
        if not self.mcp_twin_audience.startswith("mcp:"):
            raise RuntimeError("INVARIANTE STD-SEC-006: MCP_TWIN_AUDIENCE deve ser 'mcp:<namespace>'")
        if self.runtime_env == "cloud" and not self.url_admin_twin_jwks:
            raise RuntimeError("INVARIANTE STD-SEC-006: URL_ADMIN_TWIN_JWKS é obrigatório em cloud")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Retorna instância singleton de Settings."""
    return Settings()
