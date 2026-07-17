"""Domínio *audit* do server consolidado devteam-mcp (system; auditoria/compliance).

Fatia de negócio migrada (strangler, fiel) do antigo ``audit-mcp-server``: executa a
auditoria de conformidade de um repo/ambiente (checkers de estrutura/testes/segurança/
docs/lint contra as ``policies/`` YAML por ambiente) e PERSISTE auditorias, itens,
aprovações e criticidade por serviço (tenant-scoped, dual-db, credencial-zero via
``AuditStore``). As tools recebem também a ``AuditSettings`` de compute (token/org do
GitHub e ``policies_path``) — dep de RUNTIME construída no ``catalog.dispatch``. O boot/
serve/segurança (FastAPI, inner token, tenant plumbing, logging) é do AGREGADOR
(``src/server/mcp_server.py``); este pacote só expõe ``plugin.register()``. ``tools/``/
``db/``/``models/``/``checkers/``/``knowledge/``/``config/settings.py``/``policies/`` são
cópia byte-a-byte do server-fonte.
"""
