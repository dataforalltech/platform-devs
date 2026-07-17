"""Plugin do domínio *qa* — contrato ``register()`` consumido pelo agregador.

Espelha o padrão do domínio *architecture* (ver ``MCP_DEVTEAM_CONSOLIDATION_DESIGN.md``):
o agregador (``src/server/mcp_server.py``) NÃO conhece a lógica do domínio — só mescla os
``schemas`` (chaves já prefixadas ``qa_<op>`` → sem colisão entre domínios) e roteia por
prefixo (longest-match). ``register()`` devolve ``{name, schemas, dispatch, ensure_schema}``.

O ``_dispatch`` recebe o nome JÁ prefixado e a sessão tenant-scoped; CONSTRÓI a ``QAStore``
sobre a sessão, obtém os knobs de compute (``get_settings`` — só ``QA_*``, o resto é do
agregador), retira o prefixo e delega ao ``catalog.dispatch`` (roteamento byte-a-byte do
server-fonte). ``ensure_schema`` bootstrapa a tabela ``test_runs`` no pool do tenant.
"""

from __future__ import annotations

from typing import Any

from . import catalog
from .catalog import DOMAIN, get_settings
from .db.schema import ensure_schema
from .db.store import QAStore

# Prefixo de tool do domínio (``qa_``). O agregador descobre o domínio por
# longest-prefix-match (``name.startswith(f"{DOMAIN}_")``) — ``qa`` não colide com
# ``qa-engineer`` (o separador é ``_``; ``qa-engineer_x`` não começa com ``qa_``).
_PREFIX = f"{DOMAIN}_"


async def _dispatch(name: str, args: dict[str, Any], session: Any) -> dict[str, Any]:
    """Constrói a Store do domínio sobre a sessão, retira o prefixo e delega ao catálogo.

    O agregador chama ``dispatch(tool_name, args, session)`` com o nome JÁ prefixado
    (``qa_run_unit_tests``) e a sessão tenant-scoped; construímos aqui a ``QAStore``
    (single-store) e os knobs de compute (``get_settings``), e o catálogo roteia por nome
    de op sem prefixo (``run_unit_tests``) — tolera ambas as formas (idempotente se o
    prefixo faltar)."""
    op = name[len(_PREFIX) :] if name.startswith(_PREFIX) else name
    store = QAStore(session)
    settings = get_settings()
    return await catalog.dispatch(op, args, settings, store)


def register() -> dict[str, Any]:
    """Contrato do plugin consumido pelo agregador (ver docstring do módulo)."""
    schemas = {f"{_PREFIX}{op}": meta for op, meta in catalog._TOOL_SCHEMAS.items()}
    return {
        "name": DOMAIN,
        "schemas": schemas,
        "dispatch": _dispatch,
        "ensure_schema": ensure_schema,
    }
