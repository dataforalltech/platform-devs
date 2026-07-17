"""Plugin do domínio *dev-twin* — contrato ``register()`` do server consolidado.

Espelha o padrão dos demais domínios (ver MCP_DEVTEAM_CONSOLIDATION_DESIGN.md): expõe um
``register() -> dict`` que o agregador (``src/server/mcp_server.py``) consome. O agregador
NÃO conhece a lógica do domínio — só mescla os ``schemas`` (chaves já prefixadas
``dev-twin_<op>`` → sem colisão entre domínios) e roteia por prefixo (longest-match,
robusto a chaves com hífen).

``register()`` devolve:
  * ``name``       — a chave do domínio (``dev-twin``); o agregador acha o domínio por
                     ``name.startswith(f"{DOMAIN}_")``.
  * ``schemas``    — o ``catalog._TOOL_SCHEMAS`` com as CHAVES prefixadas
                     (``status`` → ``dev-twin_status``). Cada meta já traz capability
                     (``devteam-mcp.dev-twin_<op>``), required_scope
                     (``dev-twin:<recurso>:<ação>``), resource_type, data_domain, desc e
                     schema (type=object).
  * ``dispatch``   — ``async fn(name, args, session)``: recebe o nome JÁ prefixado e a
                     sessão tenant-scoped; CONSTRÓI a ``TokenStore`` da sessão (single-store),
                     retira o prefixo e delega ao ``catalog.dispatch``. As tools de sessão/
                     status ignoram o store; authenticate e as admin tools o usam.
  * ``ensure_schema`` — bootstrap idempotente da tabela ``agent_tokens`` no pool do tenant
                     (o agregador chama o ``ensure_schema`` de CADA domínio no mesmo pool).
"""

from __future__ import annotations

from typing import Any

from . import catalog
from .catalog import DOMAIN
from .db.schema import ensure_schema
from .db.store import TokenStore

# Prefixo de tool do domínio (``dev-twin_``). O agregador descobre o domínio por
# longest-prefix-match (``name.startswith(f"{DOMAIN}_")``) → o prefixo/chave PODE ter hífen.
_PREFIX = f"{DOMAIN}_"


async def _dispatch(name: str, args: dict[str, Any], session: Any) -> dict[str, Any]:
    """Constrói a Store do domínio sobre a sessão, retira o prefixo e delega ao catálogo.

    O agregador chama ``dispatch(tool_name, args, session)`` com o nome JÁ prefixado
    (``dev-twin_authenticate``) e a sessão tenant-scoped; construímos aqui a ``TokenStore``
    (single-store) e o catálogo roteia por nome de op sem prefixo (``authenticate``) —
    tolera ambas as formas (idempotente se o prefixo faltar)."""
    op = name[len(_PREFIX) :] if name.startswith(_PREFIX) else name
    store = TokenStore(session)
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
