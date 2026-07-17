"""Settings de negócio do domínio dev-twin (consolidado no devteam-mcp).

No server-fonte (``dev-twin-mcp-server``) havia um único ``DevTwinSettings`` que misturava
infra (DB/admin/gateway/logging) com o ``admin_token`` das operações de token. No server
AGREGADOR a infra é COMPARTILHADA (``src/config/settings.py`` da raiz do devteam-mcp,
``DevteamSettings``) — portanto NÃO copiamos o ``settings.py`` do fonte. Resta aqui APENAS
o knob de negócio que as tools admin copiadas byte-a-byte referenciam (via o ``catalog``):

  * ``admin_token`` — token administrativo das operações de provisão de token
                      (``register``/``revoke``/``rotate``/``list_tokens``). A definição do
                      campo (default/alias de env ``TWIN_ADMIN_TOKEN``) é preservada do
                      fonte para que o gate de admin fique idêntico.

Nenhum valor de credencial/infra vive aqui.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Knob de negócio do domínio dev-twin: admin_token das operações de token."""

    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", case_sensitive=False, populate_by_name=True
    )

    # Admin token das operações de provisão de token (register/revoke/rotate/list).
    admin_token: str = Field(default="", validation_alias="TWIN_ADMIN_TOKEN")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Retorna instância singleton de Settings (knob de negócio)."""
    return Settings()
