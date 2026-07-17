"""Domínio *devops* do server consolidado devteam-mcp (persona/IaC).

Fatia de negócio migrada do antigo ``devops-mcp-server`` (padrão strangler): persiste
artefatos IaC/pipelines/deployments/environments/service configs num MySQL via
``DevopsStore`` (tenant-scoped, dual-db, credencial-zero) e expõe geradores
determinísticos (COMPUTE PURO). O boot/serve/segurança (FastAPI, inner token, tenant
plumbing) é do AGREGADOR (``src/server/mcp_server.py``), compartilhado por todos os
domínios; este pacote só expõe ``plugin.register()``.
"""
