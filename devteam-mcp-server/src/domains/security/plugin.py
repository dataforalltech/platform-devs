"""Plugin do domínio *security* — contrato ``register()`` do server consolidado.

Espelha o padrão do domínio *architecture* (ver MCP_DEVTEAM_CONSOLIDATION_DESIGN.md):
cada `src/domains/<domain>/plugin.py` expõe um ``register() -> dict`` que o agregador
(`src/server/mcp_server.py`) consome. O agregador NÃO conhece a lógica de nenhum
domínio — só mescla os ``schemas`` (chaves já prefixadas ``<domain>_<op>`` → sem
colisão entre domínios) e roteia por prefixo.

``register()`` devolve:
  * ``name``       — a chave do domínio (``security``); o agregador acha o domínio por
                     longest-prefix-match (``name.startswith(f"{DOMAIN}_")``).
  * ``schemas``    — o ``catalog._TOOL_SCHEMAS`` com as CHAVES prefixadas
                     (``save_threat_model`` → ``security_save_threat_model``). Cada meta já
                     traz capability (``devteam-mcp.security_<op>``), required_scope
                     (``security:<res>:<ação>``), resource_type, data_domain, desc e schema.
  * ``dispatch``   — ``async fn(name, args, session)``: recebe o nome JÁ prefixado e a
                     sessão tenant-scoped; CONSTRÓI a ``SecurityStore`` sobre a sessão,
                     retira o prefixo e delega ao ``catalog.dispatch``.
  * ``ensure_schema`` — bootstrap idempotente das tabelas do domínio no pool do tenant.
"""

from __future__ import annotations

from typing import Any

from . import catalog
from .catalog import DOMAIN
from .db.schema import ensure_schema
from .db.store import SecurityStore

# Prefixo de tool do domínio (``security_``). O agregador descobre o domínio por
# longest-prefix-match (``name.startswith(f"{DOMAIN}_")``) → o prefixo/chave PODE ter hífen.
_PREFIX = f"{DOMAIN}_"


async def _dispatch(name: str, args: dict[str, Any], session: Any) -> dict[str, Any]:
    """Constrói a Store do domínio sobre a sessão, retira o prefixo e delega ao catálogo.

    O agregador chama ``dispatch(tool_name, args, session)`` com o nome JÁ prefixado
    (``security_save_threat_model``) e a sessão tenant-scoped; construímos aqui a
    ``SecurityStore`` (single-store) e o catálogo roteia por nome de op sem prefixo
    (``save_threat_model``) — tolera ambas as formas (idempotente se o prefixo faltar)."""
    op = name[len(_PREFIX) :] if name.startswith(_PREFIX) else name
    store = SecurityStore(session)
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
