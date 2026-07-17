"""Config *compute-only* do domínio ai-governance (consolidado no devteam-mcp).

A infra (DB/admin/gateway/logging) é COMPARTILHADA pelo agregador (``src/config`` da
raiz do devteam-mcp); aqui ficam APENAS os knobs compute-only que as tools copiadas do
domínio referenciam byte-a-byte (``..config.settings.get_settings``): o caminho da
knowledge-base read-only e os limites da busca textual. Nada de credencial/infra.
"""

from .settings import Settings, get_settings

__all__ = ["Settings", "get_settings"]
