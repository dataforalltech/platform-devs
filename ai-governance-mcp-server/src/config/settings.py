"""Configuração do servidor — lida do ambiente, sem hardcode."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_KB_PATH = _PROJECT_ROOT / "knowledge-base"


class Settings(BaseSettings):
    """Configuração do servidor MCP. Todos os valores têm default seguro."""

    model_config = SettingsConfigDict(
        env_prefix="GOVERNANCE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Retorna instância singleton de Settings."""
    return Settings()
