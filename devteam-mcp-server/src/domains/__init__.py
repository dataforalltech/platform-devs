"""Registry dos domínios ativos do devteam-mcp (server AGREGADOR).

``DOMAINS`` é a lista dos ``register()`` dos domínios plugados. Adicionar um domínio =
importar seu ``plugin`` e anexar ``plugin.register()`` aqui (fan-out da Fase 2 — 1
agente por domínio). O agregador (`src/server/mcp_server.py`) consome esta lista:
mescla os ``schemas`` (chaves já prefixadas ``<domain>_<op>`` → sem colisão entre
domínios), roteia o dispatch por prefixo e chama o ``ensure_schema`` de CADA domínio no
pool do tenant.

Por ora só o piloto ``architecture`` está plugado.
"""

from __future__ import annotations

from typing import Any

from .architecture import plugin as _architecture

# Lista dos domínios ativos (cada item é o dict de ``plugin.register()``).
DOMAINS: list[dict[str, Any]] = [
    _architecture.register(),
]

__all__ = ["DOMAINS"]
