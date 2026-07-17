"""Domínio *test* do server consolidado devteam-mcp (padrão strangler).

Expõe ``plugin.register()`` (contrato consumido pelo agregador em
``src/server/mcp_server.py``): planos de teste, cenários, checklists, bugs/findings e
validação (double_check / status) persistidos tenant-scoped (``TestStore``). Cópia fiel
do ``test-mcp-server`` — só o boot/serve/segurança (FastAPI, inner-token,
settings/logging) ficou no agregador.
"""
