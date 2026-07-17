"""Domínio *dev-twin* do devteam-mcp (server AGREGADOR) — auth/token de twin.

Fatia de negócio do antigo ``dev-twin-mcp-server`` consolidada como sub-pacote (padrão
strangler): ``plugin.register()`` expõe o contrato consumido pelo agregador
(``src/server/mcp_server.py``); ``catalog.py`` traz o ``_TOOL_SCHEMAS`` + o ``dispatch``
(roteamento op → handler) e ``db/``/``models.py``/``knowledge/``/``tools/`` são copiados
byte-a-byte do server-fonte. Só o boot/serve/segurança (FastAPI, inner-token,
settings/logging de infra) ficou no agregador, compartilhado por todos os domínios.

``dev-twin`` é STATEFUL: gerencia a tabela ``agent_tokens`` de identidade/tokens de
agentes (register/revoke/rotate/list) via a Store do domínio ``db.store.TokenStore``
(tenant-scoped, dual-db, credencial-zero), construída DA SESSÃO por-request. As tools de
sessão em memória (whoami/get_twin_context/refresh_context/context_status) e o ``status``
operacional leem apenas o ``SessionManager`` singleton e ignoram a Store. O único knob de
negócio não-infra (``admin_token`` = ``TWIN_ADMIN_TOKEN``) vive em ``config/settings.py``.
"""
