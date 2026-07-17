"""Settings *compute-only* do domínio ai-governance (consolidado no devteam-mcp).

No server-fonte (``ai-governance-mcp-server``) havia um único ``Settings`` que misturava
infra (DB/admin/gateway/logging) com os knobs de compute da knowledge-base. No server
AGREGADOR a infra é COMPARTILHADA (``src/config/settings.py`` da raiz do devteam-mcp,
``DevteamSettings``) — portanto NÃO copiamos o ``settings.py`` do fonte. Restam aqui
apenas os knobs compute-only que as tools copiadas byte-a-byte referenciam via
``..config.settings.get_settings``:

  * ``kb_path``              — pasta read-only Markdown/YAML da base de conhecimento
                              (empacotada ao lado do domínio; overridável por env).
  * ``search_*``            — limites/tamanho de snippet da busca textual
                              (``repository_tool.search_governance_knowledge``).

As definições de campo (defaults/bounds/alias de env) são preservadas do fonte para que
o comportamento de compute fique idêntico. Nenhum valor de credencial/infra vive aqui.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# KB empacotada com o domínio (auto-contida): ``src/domains/ai-governance/knowledge-base``.
_DOMAIN_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_KB_PATH = _DOMAIN_ROOT / "knowledge-base"


class Settings(BaseSettings):
    """Knobs compute-only da knowledge-base (read-only) — env prefix ``GOVERNANCE_``."""

    model_config = SettingsConfigDict(
        env_prefix="GOVERNANCE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,
    )

    # ── Knowledge base / governança (compute-only; read-only, git-trackeada) ──
    kb_path: Path = Field(
        default=_DEFAULT_KB_PATH,
        description="Pasta com os arquivos Markdown/YAML da base de conhecimento (read-only).",
    )
    search_max_limit: int = Field(default=20, ge=1, le=100)
    search_default_limit: int = Field(default=5, ge=1, le=50)
    search_snippet_length: int = Field(default=400, ge=80, le=4000)

    @field_validator("kb_path")
    @classmethod
    def _resolve_kb_path(cls, v: Path) -> Path:
        return v.expanduser().resolve()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Retorna instância singleton de Settings (compute-only)."""
    return Settings()
