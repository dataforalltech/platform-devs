"""Plugin do domínio *qa-engineer* — contrato ``register()`` do server consolidado.

Espelha o padrão do domínio *architecture* (ver MCP_DEVTEAM_CONSOLIDATION_DESIGN.md):
``register() -> dict`` é consumido pelo agregador (`src/server/mcp_server.py`), que só
mescla os ``schemas`` (chaves já prefixadas ``qa-engineer_<op>`` → sem colisão entre
domínios) e roteia por prefixo.

``register()`` devolve:
  * ``name``       — a chave do domínio (``qa-engineer``); o agregador acha o domínio por
                     longest-prefix-match (``name.startswith(f"{DOMAIN}_")``), robusto a
                     chaves com hífen.
  * ``schemas``    — o ``catalog._TOOL_SCHEMAS`` com as CHAVES prefixadas
                     (``save_test_plan`` → ``qa-engineer_save_test_plan``). Cada meta já
                     traz capability (``devteam-mcp.qa-engineer_<op>``), required_scope
                     (``qa-engineer:<res>:<ação>``), resource_type, data_domain, desc e
                     schema (type=object).
  * ``dispatch``   — ``async fn(name, args, session)``: recebe o nome JÁ prefixado e a
                     sessão tenant-scoped; CONSTRÓI a ``QAEngineerStore`` sobre a sessão,
                     retira o prefixo e delega ao ``catalog.dispatch`` (roteamento
                     copiado do server-fonte, byte-a-byte).
  * ``ensure_schema`` — bootstrap idempotente das tabelas do domínio no pool do tenant.
"""

from __future__ import annotations

from typing import Any

from . import catalog
from .catalog import DOMAIN
from .db.schema import ensure_schema
from .db.store import QAEngineerStore

# Prefixo de tool do domínio (``qa-engineer_``). O agregador descobre o domínio por
# longest-prefix-match (``name.startswith(f"{DOMAIN}_")``) → o prefixo/chave PODE ter hífen.
_PREFIX = f"{DOMAIN}_"


async def _dispatch(name: str, args: dict[str, Any], session: Any) -> dict[str, Any]:
    """Constrói a Store do domínio sobre a sessão, retira o prefixo e delega ao catálogo.

    O agregador chama ``dispatch(tool_name, args, session)`` com o nome JÁ prefixado
    (``qa-engineer_save_test_plan``) e a sessão tenant-scoped; construímos aqui a
    ``QAEngineerStore`` (single-store) e o catálogo roteia por nome de op sem prefixo
    (``save_test_plan``) — tolera ambas as formas (idempotente se o prefixo faltar)."""
    op = name[len(_PREFIX) :] if name.startswith(_PREFIX) else name
    store = QAEngineerStore(session)
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
