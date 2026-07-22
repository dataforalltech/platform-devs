"""Domínio *guardian* do server consolidado devteam-mcp (ADR-018).

O DevTeam como **guardião das diretrizes**: princípios, ADRs, decisões de plataforma,
standards (RFC2119), arquitetura de referência e runbooks — persistidos como software
(CRUD tipado, versionado, tenant-scoped), NÃO como blobs de arquivo soltos. Expõe
``plugin.register()`` (contrato consumido pelo agregador em ``src/server/mcp_server.py``).

Fase 1 (ADR-018): o núcleo versionado das diretrizes (`gov_directive` +
`gov_directive_version`) e os dados de referência (kinds/status).
"""
