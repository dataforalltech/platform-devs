"""Domínio *qa* do server consolidado devteam-mcp (system; runners de QA).

Fatia de negócio migrada (strangler, fiel) do antigo ``qa-mcp-server``: executa testes e
análises (unit/e2e/api, linter/security/deps/type-check/complexity, screenshot/a11y/visual,
coverage/report) e PERSISTE cada execução num log append-only ``test_runs`` (tenant-scoped,
dual-db, credencial-zero via ``QAStore``). As tools são compute + store — recebem também os
knobs ``QA_*`` de compute (thresholds/timeouts/dirs). O boot/serve/segurança (FastAPI, inner
token, tenant plumbing, settings/logging) é do AGREGADOR (``src/server/mcp_server.py``); este
pacote só expõe ``plugin.register()``. O DOMAIN é ``qa`` — não colide com ``qa-engineer`` (o
separador de prefixo é ``_`` e ``qa-engineer`` começa com ``qa-``, não ``qa_``).
"""
