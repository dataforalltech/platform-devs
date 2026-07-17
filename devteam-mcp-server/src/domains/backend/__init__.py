"""Domínio *backend* do server consolidado devteam-mcp (padrão strangler).

Expõe ``plugin.register()`` (contrato consumido pelo agregador em
``src/server/mcp_server.py``): contratos de API, schemas de banco, políticas de auth,
artefatos de código e reviews persistidos tenant-scoped (``BackendStore``), mais os
geradores determinísticos (compute puro). Cópia fiel do ``backend-mcp-server`` — só o
boot/serve/segurança (FastAPI, inner-token, settings/logging) ficou no agregador.
"""
