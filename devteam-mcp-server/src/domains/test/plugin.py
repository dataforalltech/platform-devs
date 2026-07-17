"""Plugin do domínio *test* — contrato ``register()`` do server consolidado devteam-mcp.

Espelha o padrão de referência (``src/domains/architecture/plugin.py``): expõe um
``register() -> dict`` que o agregador (`src/server/mcp_server.py`) consome. O agregador
NÃO conhece a lógica do domínio — só mescla os ``schemas`` (chaves já prefixadas
``test_<op>`` → sem colisão entre domínios) e roteia por prefixo (longest-match).

``register()`` devolve:
  * ``name``       — a chave do domínio (``test``); o agregador acha o domínio por
                     longest-prefix-match (``name.startswith(f"{DOMAIN}_")``).
  * ``schemas``    — o ``catalog._TOOL_SCHEMAS`` com as CHAVES prefixadas
                     (``create_test_plan`` → ``test_create_test_plan``). Cada meta já traz
                     capability (``devteam-mcp.test_<op>``), required_scope
                     (``test:<res>:<ação>``), resource_type, data_domain, desc e schema.
  * ``dispatch``   — ``async fn(name, args, session)``: recebe o nome JÁ prefixado e a
                     sessão tenant-scoped; CONSTRÓI a ``TestStore`` sobre a sessão, retira o
                     prefixo e delega ao ``catalog.dispatch`` (lógica copiada byte-a-byte).
  * ``ensure_schema`` — bootstrap idempotente das tabelas do domínio no pool do tenant.
"""

from __future__ import annotations

from typing import Any

from . import catalog
from .catalog import DOMAIN
from .db.schema import ensure_schema
from .db.store import TestStore

# Prefixo de tool do domínio (``test_``). O agregador descobre o domínio por
# longest-prefix-match (``name.startswith(f"{DOMAIN}_")``).
_PREFIX = f"{DOMAIN}_"


async def _dispatch(name: str, args: dict[str, Any], session: Any) -> dict[str, Any]:
    """Constrói a Store do domínio sobre a sessão, retira o prefixo e delega ao catálogo.

    O agregador chama ``dispatch(tool_name, args, session)`` com o nome JÁ prefixado
    (``test_create_test_plan``) e a sessão tenant-scoped; construímos aqui a ``TestStore``
    (single-store) e o catálogo roteia por nome de op sem prefixo (``create_test_plan``) —
    tolera ambas as formas (idempotente se o prefixo faltar)."""
    op = name[len(_PREFIX) :] if name.startswith(_PREFIX) else name
    store = TestStore(session)
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
