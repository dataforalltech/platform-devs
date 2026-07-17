"""Domínio *services* do server consolidado devteam-mcp (padrão strangler).

Expõe ``plugin.register()`` (contrato consumido pelo agregador em
``src/server/mcp_server.py``): registry de serviços/infra, descoberta (docker/portas),
health checks, gateway map, launch/stop, edição de ``.env`` e status de brokers,
persistidos tenant-scoped (``ServiceStore``). Cópia fiel do ``services-mcp-server`` — só o
boot/serve/segurança (FastAPI, inner-token, settings/logging compartilhados) ficou no
agregador; ``settings`` (defaults de tuning ``docker_timeout``/``health_timeout``) é dep de
RUNTIME construída no ``catalog.dispatch``.
"""
