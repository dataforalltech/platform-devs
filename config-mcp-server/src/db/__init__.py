"""Camada de persistência do config-mcp sobre o ORM canônico (`platform_database.orm`).

Contém o bootstrap de schema por-tenant (``schema.ensure_schema``) e o ``ConfigStore``
async (``store.ConfigStore``) — ambos tenant-scoped e credencial-zero (dual-db).
"""

from __future__ import annotations
