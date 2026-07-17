"""Domínio *product-owner* do devteam-mcp (server AGREGADOR).

Fatia de negócio do antigo ``product-owner-mcp-server`` consolidada como sub-pacote
(padrão strangler): ``plugin.register()`` expõe o contrato consumido pelo agregador
(``src/server/mcp_server.py``); ``catalog.py`` traz o ``_TOOL_SCHEMAS`` + o ``dispatch``
(roteamento op → handler) e ``db/``/``models.py``/``tools/`` são copiados byte-a-byte do
server-fonte. A Store do domínio é ``db.store.ProductOwnerStore`` (tenant-scoped,
dual-db, credencial-zero).
"""
