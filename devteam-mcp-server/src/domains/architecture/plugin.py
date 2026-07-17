"""Plugin do domínio *architecture* — contrato ``register()`` do server consolidado.

Padrão a replicar nos 19 domínios restantes (ver MCP_DEVTEAM_CONSOLIDATION_DESIGN.md):
cada `src/domains/<domain>/plugin.py` expõe um ``register() -> dict`` que o agregador
(`src/server/mcp_server.py`) consome. O agregador NÃO conhece a lógica de nenhum
domínio — só mescla os ``schemas`` (chaves já prefixadas ``<domain>_<op>`` → sem
colisão entre domínios) e roteia por prefixo.

``register()`` devolve:
  * ``name``       — a chave do domínio (``architecture``); o agregador acha o domínio
                     por longest-prefix-match (``name.startswith(f"{DOMAIN}_")``), robusto a
                     chaves com hífen (``product-owner``, ``ai-governance``, ``dev-twin``).
  * ``schemas``    — o ``catalog._TOOL_SCHEMAS`` com as CHAVES prefixadas
                     (``save_artifact`` → ``architecture_save_artifact``). Cada meta já
                     traz capability (``devteam-mcp.architecture_<op>``), required_scope
                     (``architecture:<res>:<ação>``), resource_type, data_domain, desc e
                     schema (type=object).
  * ``dispatch``   — ``async fn(name, args, session)``: recebe o nome JÁ prefixado e a
                     sessão tenant-scoped; CONSTRÓI a(s) Store(s) do domínio sobre a sessão,
                     retira o prefixo e delega ao ``catalog.dispatch`` (lógica de roteamento
                     copiada do server-fonte, byte-a-byte). O domínio é DONO das suas Stores
                     → contrato uniforme p/ single-store (aqui) e multi-store (ai-governance,
                     que constrói várias Stores da mesma sessão).
  * ``ensure_schema`` — bootstrap idempotente das tabelas do domínio no pool do tenant
                     (o agregador chama o ``ensure_schema`` de CADA domínio no mesmo pool).
"""

from __future__ import annotations

from typing import Any

from . import catalog
from .catalog import DOMAIN
from .db.schema import ensure_schema
from .db.store import ArchitectureStore

# Prefixo de tool do domínio (``architecture_``). O agregador descobre o domínio por
# longest-prefix-match (``name.startswith(f"{DOMAIN}_")``) → o prefixo/chave PODE ter hífen.
_PREFIX = f"{DOMAIN}_"


async def _dispatch(name: str, args: dict[str, Any], session: Any) -> dict[str, Any]:
    """Constrói a Store do domínio sobre a sessão, retira o prefixo e delega ao catálogo.

    O agregador chama ``dispatch(tool_name, args, session)`` com o nome JÁ prefixado
    (``architecture_save_artifact``) e a sessão tenant-scoped; construímos aqui a
    ``ArchitectureStore`` (single-store) e o catálogo roteia por nome de op sem prefixo
    (``save_artifact``) — tolera ambas as formas (idempotente se o prefixo faltar)."""
    op = name[len(_PREFIX) :] if name.startswith(_PREFIX) else name
    store = ArchitectureStore(session)
    return await catalog.dispatch(op, args, store)


def register() -> dict[str, Any]:
    """Contrato do plugin consumido pelo agregador (ver docstring do módulo)."""
    schemas = {f"{_PREFIX}{op}": meta for op, meta in catalog._TOOL_SCHEMAS.items()}
    return {
        "name": DOMAIN,
        "schemas": schemas,
        "dispatch": _dispatch,
        "ensure_schema": ensure_schema,
    }
