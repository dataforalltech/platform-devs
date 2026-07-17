"""Domínio *infra* do server consolidado devteam-mcp (padrão strangler).

Migração (fiel) do antigo `infra-mcp-server`: a lógica de negócio (tools compute-only sobre
CLIs terraform/checkov/infracost + o VM allocator persistido no ORM canônico, com db/models/
utils/knowledge/config.secrets) foi copiada byte-a-byte; só o boot/serve/segurança (FastAPI,
inner-token, settings/logging compartilhados) ficou no agregador. O `plugin.register()` expõe
as 15 tools já prefixadas (`infra_<op>`) e o `dispatch`; ver `catalog.py`.

`infra` é COMPUTE + STATEFUL: as 6 tools compute-only (terraform/checkov/infracost) rodam CLIs
locais em thread e não tocam dados do tenant; as 9 tools do **allocator** persistem 100% sobre
o ORM canônico (dual-db, tenant-scoped, credencial-zero) via o `AllocatorStore` construído da
sessão do tenant. O provisioner (terraform/mock) e o segredo Fernet (cifra chaves SSH) são
deps de RUNTIME nível-de-processo, construídas no `catalog`.
"""
