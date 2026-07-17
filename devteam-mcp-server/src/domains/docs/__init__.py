"""Domínio *docs* do devteam-mcp (server AGREGADOR) — index/scan/validação/auditoria de docs.

Migração (strangler, fiel) do antigo `docs-mcp-server`: a lógica de negócio (tools, db,
models, knowledge/standards+templates) foi copiada byte-a-byte; só o boot/serve/segurança
(FastAPI, inner-token, tenant plumbing) ficou no agregador. O `plugin.register()` expõe as
14 tools já prefixadas (`docs_<op>`) e o `dispatch` tenant-scoped; ver `catalog.py`.

`docs` é COMPUTE + STATEFUL: as tools indexam/validam/auditam documentação de um repo (I/O
de arquivos, git) e persistem o índice de docs e o histórico de auditoria num store próprio
(dual-db, tenant-scoped, credencial-zero) via a `DocsStore` construída da sessão do tenant.
Os `settings` (thresholds/flags do domínio) são uma dep de RUNTIME construída no `catalog`.
"""
