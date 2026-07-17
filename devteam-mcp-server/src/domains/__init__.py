"""Registry dos domínios ativos do devteam-mcp (server AGREGADOR).

**Auto-discovery:** cada subpacote ``src/domains/<domain>/`` que exponha
``plugin.register()`` é plugado automaticamente. Adicionar um domínio = soltar o
pacote (NÃO edite este arquivo — evita conflito no fan-out de 1 agente por domínio).

O agregador (``src/server/mcp_server.py``) consome ``DOMAINS``: mescla os ``schemas``
(chaves já prefixadas ``<domain>_<op>`` → sem colisão entre domínios), roteia o dispatch
por prefixo (longest-match) e chama o ``ensure_schema`` de CADA domínio no pool do tenant.

Cada ``register()`` retorna ``{name, schemas, dispatch, store_cls, ensure_schema}``.
"""

from __future__ import annotations

import importlib
import pkgutil
from typing import Any

DOMAINS: list[dict[str, Any]] = []

for _mod in pkgutil.iter_modules(__path__):
    if not _mod.ispkg:
        continue
    _plugin = importlib.import_module(f"{__name__}.{_mod.name}.plugin")
    DOMAINS.append(_plugin.register())

# Ordem determinística por nome do domínio (estabilidade de output/listagem).
DOMAINS.sort(key=lambda d: d["name"])

__all__ = ["DOMAINS"]
