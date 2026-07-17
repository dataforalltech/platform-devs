"""Plugin do domínio *infra* — contrato ``register()`` do server consolidado.

Espelha o padrão do domínio *architecture* (ver MCP_DEVTEAM_CONSOLIDATION_DESIGN.md): o
agregador (`src/server/mcp_server.py`) consome ``register()``, mescla os ``schemas`` (chaves
já prefixadas ``infra_<op>`` → sem colisão entre domínios), roteia o dispatch por prefixo e
chama o ``ensure_schema`` de CADA domínio no pool do tenant.

``register()`` devolve:
  * ``name``       — a chave do domínio (``infra``); o agregador acha o domínio por
                     longest-prefix-match (``name.startswith(f"{DOMAIN}_")``).
  * ``schemas``    — o ``catalog._TOOL_SCHEMAS`` com as CHAVES prefixadas (``request_vm`` →
                     ``infra_request_vm``). Cada meta já traz capability
                     (``devteam-mcp.infra_<op>``), required_scope (``infra:<res>:<ação>``),
                     resource_type, data_domain, description e schema (type=object).
  * ``dispatch``   — ``async fn(name, args, session)``: recebe o nome JÁ prefixado e a
                     sessão tenant-scoped; retira o prefixo e delega ao ``catalog.dispatch``,
                     que roteia compute-only × allocator e constrói o ``AllocatorStore`` da
                     sessão (com as deps de RUNTIME provisioner/fernet/policy nível-de-processo).
  * ``ensure_schema`` — bootstrap idempotente das tabelas do allocator no pool do tenant.
"""

from __future__ import annotations

from typing import Any

from . import catalog
from .catalog import DOMAIN
from .db.schema import ensure_schema

# Prefixo de tool do domínio (``infra_``). O agregador descobre o domínio por
# longest-prefix-match (``name.startswith(f"{DOMAIN}_")``).
_PREFIX = f"{DOMAIN}_"


async def _dispatch(name: str, args: dict[str, Any], session: Any) -> dict[str, Any]:
    """Retira o prefixo do domínio e delega ao catálogo, passando a sessão tenant-scoped.

    O agregador chama ``dispatch(tool_name, args, session)`` com o nome JÁ prefixado
    (``infra_request_vm``) e a sessão tenant-scoped. NÃO construímos a Store aqui: o
    ``AllocatorStore`` precisa das deps de RUNTIME (provisioner/fernet/policy, nível de
    processo) e só as tools do allocator abrem Store — o ``catalog.dispatch`` decide isso
    (roteando compute-only × allocator) e constrói a Store da sessão quando necessário.
    O catálogo roteia por nome de op sem prefixo (``request_vm``) — tolera ambas as formas
    (idempotente se o prefixo faltar)."""
    op = name[len(_PREFIX) :] if name.startswith(_PREFIX) else name
    return await catalog.dispatch(op, args, session)


def register() -> dict[str, Any]:
    """Contrato do plugin consumido pelo agregador (ver docstring do módulo)."""
    schemas = {f"{_PREFIX}{op}": meta for op, meta in catalog._TOOL_SCHEMAS.items()}
    return {
        "name": DOMAIN,
        "schemas": schemas,
        "dispatch": _dispatch,
        "ensure_schema": ensure_schema,
    }
