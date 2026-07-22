"""Plugin do domínio *guardian* — contrato ``register()`` do server consolidado (ADR-018).

Espelha o padrão dos demais domínios (ver `session/plugin.py`): expõe um
``register() -> dict`` que o agregador (`src/server/mcp_server.py`) consome. O agregador
NÃO conhece a lógica do domínio — só mescla os ``schemas`` (chaves já prefixadas
``guardian_<op>`` → sem colisão) e roteia por longest-prefix-match.

``register()`` devolve:
  * ``name``       — a chave do domínio (``guardian``).
  * ``schemas``    — ``catalog._TOOL_SCHEMAS`` com as CHAVES prefixadas
                     (``create_directive`` → ``guardian_create_directive``); cada meta traz
                     capability (``devteam-mcp.guardian_<op>``), required_scope
                     (``guardian:<res>:<ação>``), resource_type, data_domain, desc e schema.
  * ``dispatch``   — ``async fn(name, args, session)``: constrói a ``GuardianStore`` sobre a
                     sessão tenant-scoped, retira o prefixo e delega ao ``catalog.dispatch``.
  * ``ensure_schema`` — bootstrap idempotente das 4 tabelas do domínio no pool do tenant.
"""

from __future__ import annotations

from typing import Any

from . import catalog
from .catalog import DOMAIN
from .db.schema import ensure_schema
from .db.store import GuardianStore

# Prefixo de tool do domínio (``guardian_``). O agregador descobre o domínio por
# longest-prefix-match (``name.startswith(f"{DOMAIN}_")``).
_PREFIX = f"{DOMAIN}_"


async def _dispatch(name: str, args: dict[str, Any], session: Any) -> dict[str, Any]:
    """Constrói a Store do domínio sobre a sessão, retira o prefixo e delega ao catálogo."""
    op = name[len(_PREFIX) :] if name.startswith(_PREFIX) else name
    store = GuardianStore(session)
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
