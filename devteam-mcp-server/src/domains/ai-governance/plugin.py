"""Plugin do domínio *ai-governance* — contrato ``register()`` do server consolidado.

Espelha o padrão dos demais domínios (ver MCP_DEVTEAM_CONSOLIDATION_DESIGN.md): expõe um
``register() -> dict`` que o agregador (``src/server/mcp_server.py``) consome. O agregador
NÃO conhece a lógica do domínio — só mescla os ``schemas`` (chaves já prefixadas
``ai-governance_<op>`` → sem colisão entre domínios) e roteia por prefixo (longest-match,
robusto a chaves com hífen).

``register()`` devolve:
  * ``name``       — a chave do domínio (``ai-governance``); o agregador acha o domínio por
                     ``name.startswith(f"{DOMAIN}_")``.
  * ``schemas``    — o ``catalog._TOOL_SCHEMAS`` com as CHAVES prefixadas
                     (``status`` → ``ai-governance_status``). Cada meta já traz capability
                     (``devteam-mcp.ai-governance_<op>``), required_scope
                     (``ai-governance:<recurso>:<verbo>``), resource_type, data_domain, desc
                     e schema (type=object).
  * ``dispatch``   — ``async fn(name, args, session)``: recebe o nome JÁ prefixado e a
                     sessão tenant-scoped; retira o prefixo e delega ao ``catalog.dispatch``,
                     que (domínio MULTI-STORE) constrói ``SuggestionStore``/``AuditStore``
                     DA sessão para as tools tenant-scoped e ignora a sessão nas compute.
  * ``ensure_schema`` — bootstrap idempotente das 2 tabelas mutáveis do domínio no pool do
                     tenant (o agregador chama o ``ensure_schema`` de CADA domínio).
"""

from __future__ import annotations

from typing import Any

from . import catalog
from .catalog import DOMAIN
from .db.schema import ensure_schema

# Prefixo de tool do domínio (``ai-governance_``). O agregador descobre o domínio por
# longest-prefix-match (``name.startswith(f"{DOMAIN}_")``) → o prefixo/chave PODE ter hífen.
_PREFIX = f"{DOMAIN}_"


async def _dispatch(name: str, args: dict[str, Any], session: Any) -> dict[str, Any]:
    """Retira o prefixo do domínio e delega ao catálogo, passando a sessão tenant-scoped.

    O agregador chama ``dispatch(tool_name, args, session)`` com o nome JÁ prefixado
    (``ai-governance_submit_suggestion``) e a sessão do tenant. Domínio multi-store: as
    Store(s) são construídas DENTRO do ``catalog.dispatch`` (a partir da sessão) só quando
    a tool é tenant-scoped; as tools compute ignoram a sessão."""
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
