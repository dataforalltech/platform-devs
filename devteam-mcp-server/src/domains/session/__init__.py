"""Domínio *session* do server consolidado devteam-mcp (padrão strangler).

Expõe ``plugin.register()`` (contrato consumido pelo agregador em
``src/server/mcp_server.py``): sessões de trabalho Claude Code, checkpoints,
artefatos, tasks, dependências de serviço, sugestões cross-repo e o audit trail de
decisões — persistidos tenant-scoped (``SessionStore``). Cópia fiel do
``session-mcp-server`` — só o boot/serve/segurança (FastAPI, inner-token,
settings/logging) ficou no agregador.
"""
