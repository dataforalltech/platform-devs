"""Camada de persistência ORM (dual-db, tenant-scoped, credencial-zero).

Este pacote carrega os DOIS únicos stores mutáveis do ai-governance sobre o ORM
canônico (`platform_database.orm`): a mural cross-repo de sugestões e a trilha de
auditoria de decisões. A knowledge-base (Markdown/YAML) continua sendo dado de
referência read-only no filesystem (ver `..knowledge`), fora do DB do tenant.
"""

from __future__ import annotations
