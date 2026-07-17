"""Domínio *deploy* do devteam-mcp (server AGREGADOR) — ledger git/PR/deploy/CI/ACR.

Migração (strangler, fiel) do antigo `deploy-mcp-server`: a lógica de negócio (tools,
db, models, knowledge/GitHubClient) foi copiada byte-a-byte; só o boot/serve/segurança
(FastAPI, inner-token, settings/logging compartilhados) ficou no agregador. O
`plugin.register()` expõe as 30 tools já prefixadas (`deploy_<op>`) e o `dispatch`
tenant-scoped; ver `catalog.py`.

`deploy` é COMPUTE + STATEFUL: cada tool de ação FAZ a operação real (git, GitHub,
deploy, ACR, CI) via o `GitHubClient` (dep de RUNTIME, PAT via env) e, após o sucesso,
**registra a operação num ledger persistido** (dual-db, tenant-scoped, credencial-zero)
via a `DeployStore` construída da sessão do tenant.
"""
