"""Plugin do domínio *devops* — contrato ``register()`` do server consolidado.

Espelha o padrão do domínio *architecture* (ver MCP_DEVTEAM_CONSOLIDATION_DESIGN.md):
`src/domains/devops/plugin.py` expõe um ``register() -> dict`` que o agregador
(`src/server/mcp_server.py`) consome. O agregador NÃO conhece a lógica do domínio — só
mescla os ``schemas`` (chaves já prefixadas ``devops_<op>`` → sem colisão entre domínios)
e roteia por prefixo.

``register()`` devolve:
  * ``name``       — a chave do domínio (``devops``); o agregador acha o domínio por
                     longest-prefix-match (``name.startswith(f"{DOMAIN}_")``).
  * ``schemas``    — o ``catalog._TOOL_SCHEMAS`` com as CHAVES prefixadas
                     (``save_artifact`` → ``devops_save_artifact``). Cada meta já traz
                     capability (``devteam-mcp.devops_<op>``), required_scope
                     (``devops:<res>:<ação>``), resource_type, data_domain, desc e schema.
  * ``dispatch``   — ``async fn(name, args, session)``: recebe o nome JÁ prefixado e a
                     sessão tenant-scoped; CONSTRÓI a ``DevopsStore`` sobre a sessão,
                     retira o prefixo e delega ao ``catalog.dispatch``.
  * ``ensure_schema`` — bootstrap idempotente das tabelas do domínio no pool do tenant.
"""

from __future__ import annotations

from typing import Any

from . import catalog
from .catalog import DOMAIN
from .db.schema import ensure_schema
from .db.store import DevopsStore

# Prefixo de tool do domínio (``devops_``). O agregador descobre o domínio por
# longest-prefix-match (``name.startswith(f"{DOMAIN}_")``) → o prefixo/chave PODE ter hífen.
_PREFIX = f"{DOMAIN}_"


async def _dispatch(name: str, args: dict[str, Any], session: Any) -> dict[str, Any]:
    """Constrói a Store do domínio sobre a sessão, retira o prefixo e delega ao catálogo.

    O agregador chama ``dispatch(tool_name, args, session)`` com o nome JÁ prefixado
    (``devops_save_artifact``) e a sessão tenant-scoped; construímos aqui a ``DevopsStore``
    (single-store) e o catálogo roteia por nome de op sem prefixo (``save_artifact``) —
    tolera ambas as formas (idempotente se o prefixo faltar)."""
    op = name[len(_PREFIX) :] if name.startswith(_PREFIX) else name
    store = DevopsStore(session)
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
