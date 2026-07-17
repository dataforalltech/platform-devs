"""Domínio *security* do server consolidado devteam-mcp (persona de segurança).

Fatia de negócio migrada (strangler, fiel) do antigo ``security-mcp-server``: persiste
modelos de ameaças, controles de segurança, avaliações CVSS e artefatos de segurança
(tenant-scoped, dual-db, credencial-zero) e expõe geradores determinísticos. O contrato
``register()`` (ver ``plugin.py``) é consumido pelo agregador ``src/server/mcp_server.py``.
"""
