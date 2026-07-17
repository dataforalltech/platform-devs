"""Domínio *ai-governance* do server consolidado devteam-mcp (padrão strangler).

Fatia de negócio migrada (fiel) do antigo ``ai-governance-mcp-server``. Domínio HÍBRIDO:
a maioria das tools é COMPUTE-ONLY sobre a knowledge-base local read-only (diretrizes,
políticas, validações, grafo do ecossistema) via o singleton ``GovernanceRepository``;
os DOIS stores mutáveis (mural cross-repo de sugestões + trilha de auditoria de decisões)
rodam tenant-scoped (dual-db, credencial-zero) sobre ``SuggestionStore``/``AuditStore``,
construídos DA SESSÃO por-request. O contrato ``register()`` (ver ``plugin.py``) é
consumido pelo agregador ``src/server/mcp_server.py``; o boot/serve/segurança (FastAPI,
inner token, settings/logging de infra) fica no agregador, compartilhado por todos os
domínios. ``tools/``/``db/``/``models/``/``knowledge/``/``utils/`` são cópia byte-a-byte
do server-fonte.
"""
