"""Domínio *pipeline* do devteam-mcp (server AGREGADOR) — promoção/gates entre ambientes.

Migração (strangler, fiel) do antigo `pipeline-mcp-server`: a lógica de negócio (tools,
db, models, config/settings) foi copiada byte-a-byte; só o boot/serve/segurança
(FastAPI, inner-token, logging compartilhado) ficou no agregador. O `plugin.register()`
expõe as 14 tools já prefixadas (`pipeline_<op>`) e o `dispatch` tenant-scoped; ver
`catalog.py`.

`pipeline` é STATEFUL + COMPUTE: persiste pipelines/gates/promoções num MySQL/PostgreSQL
tenant-scoped (dual-db, credencial-zero) via a `PipelineStore` construída da sessão do
tenant, E fala com a **GitHub REST API** para criar/mergiar PRs nas promoções (o PAT é
dep de RUNTIME, resolvido de `PipelineSettings` via env dentro da `catalog.dispatch`).

Regras de aprovação (preservadas do fonte):
  DEV  (PRs → develop):     auto-aprova e mergia autonomamente (watch_prs)
  HML  (develop → homol):   cria PR, aguarda aprovação humana (approve_promotion)
  PROD (homol → main):      cria PR, aguarda aprovação humana (approve_promotion)
"""
