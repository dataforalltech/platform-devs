"""Plugin do domínio *services* — contrato ``register()`` do server consolidado.

Espelha o padrão do domínio *architecture* (ver MCP_DEVTEAM_CONSOLIDATION_DESIGN.md): o
agregador (`src/server/mcp_server.py`) consome ``register()``, mescla os ``schemas`` (chaves
já prefixadas ``services_<op>`` → sem colisão entre domínios), roteia o dispatch por prefixo
e chama o ``ensure_schema`` de CADA domínio no pool do tenant.

``register()`` devolve:
  * ``name``       — a chave do domínio (``services``); o agregador acha o domínio por
                     longest-prefix-match (``name.startswith(f"{DOMAIN}_")``).
  * ``schemas``    — o ``catalog._TOOL_SCHEMAS`` com as CHAVES prefixadas (``register_service``
                     → ``services_register_service``). Cada meta já traz capability
                     (``devteam-mcp.services_<op>``), required_scope (``services:<res>:<ação>``),
                     resource_type, data_domain, description e schema (type=object).
  * ``dispatch``   — ``async fn(name, args, session)``: recebe o nome JÁ prefixado e a
                     sessão tenant-scoped; CONSTRÓI a ``ServiceStore`` sobre a sessão, retira o
                     prefixo e delega ao ``catalog.dispatch`` (que constrói ``settings`` — dep
                     de RUNTIME — antes de rotear).
  * ``ensure_schema`` — bootstrap idempotente da tabela ``services`` no pool do tenant.
"""

from __future__ import annotations

from typing import Any

from . import catalog
from .catalog import DOMAIN
from .db.schema import ensure_schema
from .db.store import ServiceStore

# Prefixo de tool do domínio (``services_``). O agregador descobre o domínio por
# longest-prefix-match (``name.startswith(f"{DOMAIN}_")``).
_PREFIX = f"{DOMAIN}_"


async def _dispatch(name: str, args: dict[str, Any], session: Any) -> dict[str, Any]:
    """Constrói a Store do domínio sobre a sessão, retira o prefixo e delega ao catálogo.

    O agregador chama ``dispatch(tool_name, args, session)`` com o nome JÁ prefixado
    (``services_register_service``) e a sessão tenant-scoped; construímos aqui a
    ``ServiceStore`` e o catálogo roteia por nome de op sem prefixo (``register_service``) —
    tolera ambas as formas (idempotente se o prefixo faltar)."""
    op = name[len(_PREFIX) :] if name.startswith(_PREFIX) else name
    store = ServiceStore(session)
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
