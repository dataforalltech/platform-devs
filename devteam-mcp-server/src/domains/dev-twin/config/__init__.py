"""Config do domínio dev-twin (consolidado no devteam-mcp).

A infra (DB/admin/gateway/logging) é COMPARTILHADA pelo agregador (``src/config`` da raiz
do devteam-mcp) — portanto NÃO copiamos o ``settings.py`` do fonte. Resta aqui APENAS o
knob de negócio que as tools admin (register/revoke/rotate/list_tokens) referenciam via
``..config.settings.get_settings``: o ``admin_token`` (``TWIN_ADMIN_TOKEN``). Nenhum valor
de credencial/infra vive aqui.
"""

from .settings import Settings, get_settings

__all__ = ["Settings", "get_settings"]
