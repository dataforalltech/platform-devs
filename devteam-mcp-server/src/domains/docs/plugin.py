"""Plugin do domínio *docs* — contrato ``register()`` do server consolidado.

Espelha o padrão do domínio *architecture* (ver MCP_DEVTEAM_CONSOLIDATION_DESIGN.md): o
agregador (`src/server/mcp_server.py`) consome ``register()``, mescla os ``schemas`` (chaves
já prefixadas ``docs_<op>`` → sem colisão entre domínios), roteia o dispatch por prefixo e
chama o ``ensure_schema`` de CADA domínio no pool do tenant.

``register()`` devolve:
  * ``name``       — a chave do domínio (``docs``); o agregador acha o domínio por
                     longest-prefix-match (``name.startswith(f"{DOMAIN}_")``).
  * ``schemas``    — o ``catalog._TOOL_SCHEMAS`` com as CHAVES prefixadas (``scan_docs`` →
                     ``docs_scan_docs``). Cada meta já traz capability
                     (``devteam-mcp.docs_<op>``), required_scope (``docs:<res>:<ação>``),
                     resource_type, data_domain, description e schema (type=object).
  * ``dispatch``   — ``async fn(name, args, session)``: recebe o nome JÁ prefixado e a
                     sessão tenant-scoped; CONSTRÓI a ``DocsStore`` sobre a sessão, retira o
                     prefixo e delega ao ``catalog.dispatch``. O ``catalog.dispatch`` constrói
                     o ``settings`` (dep de RUNTIME: thresholds/flags do domínio) e roteia.
  * ``ensure_schema`` — bootstrap idempotente das tabelas (audits/doc_index) no pool do tenant.
"""

from __future__ import annotations

from typing import Any

from . import catalog
from .catalog import DOMAIN
from .db.schema import ensure_schema
from .db.store import DocsStore

# Prefixo de tool do domínio (``docs_``). O agregador descobre o domínio por
# longest-prefix-match (``name.startswith(f"{DOMAIN}_")``).
_PREFIX = f"{DOMAIN}_"


async def _dispatch(name: str, args: dict[str, Any], session: Any) -> dict[str, Any]:
    """Constrói a Store do domínio sobre a sessão, retira o prefixo e delega ao catálogo.

    O agregador chama ``dispatch(tool_name, args, session)`` com o nome JÁ prefixado
    (``docs_scan_docs``) e a sessão tenant-scoped; construímos aqui a ``DocsStore``
    (single-store) e o catálogo roteia por nome de op sem prefixo (``scan_docs``) —
    tolera ambas as formas (idempotente se o prefixo faltar)."""
    op = name[len(_PREFIX) :] if name.startswith(_PREFIX) else name
    store = DocsStore(session)
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
