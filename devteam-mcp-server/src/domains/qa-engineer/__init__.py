"""Domínio *qa-engineer* do server consolidado devteam-mcp (persona de QA).

Fatia de negócio migrada (strangler, fiel) do antigo ``qa-engineer-mcp-server``:
persiste planos/casos de teste, bug reports, quality gates e artefatos de QA
(tenant-scoped, dual-db, credencial-zero) via ``QAEngineerStore`` e expõe os geradores
determinísticos (COMPUTE PURO). O contrato ``register()`` (ver ``plugin.py``) é consumido
pelo agregador ``src/server/mcp_server.py``; o boot/serve/segurança (FastAPI, inner
token, settings/logging) fica no agregador, compartilhado por todos os domínios.
"""
