"""Plugin do domínio *deploy* — contrato ``register()`` do server consolidado.

Espelha o padrão do domínio *architecture* (ver MCP_DEVTEAM_CONSOLIDATION_DESIGN.md): o
agregador (`src/server/mcp_server.py`) consome ``register()``, mescla os ``schemas`` (chaves
já prefixadas ``deploy_<op>`` → sem colisão entre domínios), roteia o dispatch por prefixo e
chama o ``ensure_schema`` de CADA domínio no pool do tenant.

``register()`` devolve:
  * ``name``       — a chave do domínio (``deploy``); o agregador acha o domínio por
                     longest-prefix-match (``name.startswith(f"{DOMAIN}_")``).
  * ``schemas``    — o ``catalog._TOOL_SCHEMAS`` com as CHAVES prefixadas (``list_repos`` →
                     ``deploy_list_repos``). Cada meta já traz capability
                     (``devteam-mcp.deploy_<op>``), required_scope (``deploy:<res>:<ação>``),
                     resource_type, data_domain, description e schema (type=object).
  * ``dispatch``   — ``async fn(name, args, session)``: recebe o nome JÁ prefixado e a
                     sessão tenant-scoped; CONSTRÓI a ``DeployStore`` sobre a sessão, retira o
                     prefixo e delega ao ``catalog.dispatch``. A ``catalog.dispatch`` faz a
                     orquestração ação→ledger do server-fonte (constrói ``settings``/
                     ``GitHubClient`` — deps de RUNTIME — para as tools de ação).
  * ``ensure_schema`` — bootstrap idempotente das tabelas do ledger no pool do tenant.
"""

from __future__ import annotations

from typing import Any

from . import catalog
from .catalog import DOMAIN
from .db.schema import ensure_schema
from .db.store import DeployStore

# Prefixo de tool do domínio (``deploy_``). O agregador descobre o domínio por
# longest-prefix-match (``name.startswith(f"{DOMAIN}_")``).
_PREFIX = f"{DOMAIN}_"


async def _dispatch(name: str, args: dict[str, Any], session: Any) -> dict[str, Any]:
    """Constrói a Store do domínio sobre a sessão, retira o prefixo e delega ao catálogo.

    O agregador chama ``dispatch(tool_name, args, session)`` com o nome JÁ prefixado
    (``deploy_list_repos``) e a sessão tenant-scoped; construímos aqui a ``DeployStore``
    (usada pelo ledger) e o catálogo roteia por nome de op sem prefixo (``list_repos``) —
    tolera ambas as formas (idempotente se o prefixo faltar)."""
    op = name[len(_PREFIX) :] if name.startswith(_PREFIX) else name
    store = DeployStore(session)
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
