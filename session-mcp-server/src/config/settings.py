from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class SessionSettings(BaseSettings):
    """Settings do session-mcp.

    O session-mcp não detém credenciais GitHub — operações git são
    domínio do deploy-mcp. Aqui guardamos apenas defaults de convenção
    (default_base_branch) que precisam ser conhecidos pelo agente.
    """

    model_config = SettingsConfigDict(
        env_prefix="SESSION_",
        env_file=".env",
        extra="ignore",
    )

    db_path: str = Field(default=str(Path.home() / ".session-mcp" / "sessions.db"))
    max_active_sessions: int = Field(default=50)
    default_list_limit: int = Field(default=20)
    default_base_branch: str = Field(
        default="develop",
        description="Branch base sugerida quando o agente cria a branch da sessão via deploy-mcp.",
    )


def get_settings() -> SessionSettings:
    return SessionSettings()
