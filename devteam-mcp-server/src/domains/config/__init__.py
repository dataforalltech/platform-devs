"""Domínio *config* do devteam-mcp — credenciais/ambientes/tenants/workspace/sysinfo.

Sub-pacote do server AGREGADOR (ver ``src/domains/__init__.py``). Expõe um
``plugin.register()`` que o agregador pluga por auto-discovery. É a persona **stateful**
``config-mcp`` migrada pelo padrão strangler: a lógica de negócio (``tools/``, ``db/``,
``knowledge/``, ``models``) é FIEL ao server-fonte; o que ficou de fora é o boot/serve/
segurança (FastAPI + inner-token + settings/logging), responsabilidade do agregador.

Persistência tenant-scoped e dual-db (credencial-zero, ORM-H-12): as tools persistem em
``config_entries`` no banco do tenant, com os valores encriptados em repouso via Fernet
(``knowledge.encryptor.Encryptor`` — defense-in-depth, o DB só guarda a cifra).
"""

from __future__ import annotations
