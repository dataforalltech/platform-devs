"""Catálogo de tools + dispatcher do domínio *dev-twin* (consolidado no devteam-mcp).

Este módulo é a fatia "de negócio" do antigo ``dev-twin-mcp-server/src/server/
mcp_server.py``: mantém intactos o ``_TOOL_SCHEMAS`` (metadados de policy por tool), o
``status`` operacional e o ``_dispatch`` (roteamento op → handler). O que ficou de FORA é
o boot/serve/segurança (FastAPI, PEP inner-token, stdio, tenant plumbing) — isso é
responsabilidade do AGREGADOR (``src/server/mcp_server.py``), compartilhado por todos os
domínios.

Diferenças vs. o server-fonte (strangler — fiel, sem inventar comportamento):
  * ``capability`` passa a ``devteam-mcp.dev-twin_<op>`` (namespace do server consolidado
    + nome de tool já prefixado pelo domínio — o gateway não deriva por nome, então a
    capability é o id estável).
  * ``required_scope`` passa a ``dev-twin:<recurso>:<ação>`` — PRESERVA o least-privilege
    por-tool do domínio, só troca o antigo prefixo de namespace ``dev-twin-mcp`` pelo
    domínio canônico ``dev-twin``. Os DEMAIS campos (``resource_type``/``data_domain``/
    ``description``/``schema``) ficam byte-a-byte do fonte. No fonte esses valores eram
    literais inline em ``_TOOL_SCHEMAS``; aqui o dict literal é o MESMO do fonte e um loop
    reescreve APENAS ``capability``/``required_scope`` para o namespace consolidado
    (uniforme, auditável) — a saída é idêntica à do fonte, mudando só os 2 campos exigidos.
  * As CHAVES de ``_TOOL_SCHEMAS`` aqui continuam os nomes de op SEM prefixo (``status``);
    o ``plugin.register()`` prefixa (``dev-twin_status``) e o ``plugin.dispatch`` retira o
    prefixo antes de chamar ``dispatch`` daqui — assim a lógica de roteamento copiada do
    server-fonte fica byte-a-byte idêntica.

NOTA: ``dev-twin`` é STATEFUL — a persistência (tabela ``agent_tokens``) roda sobre o ORM
canônico, tenant-scoped e dual-db (credencial-zero). As tools de sessão em memória
(whoami/get_twin_context/refresh_context/context_status) e o ``status`` NÃO tocam o banco;
só authenticate e as 4 admin tools usam a ``TokenStore`` (construída da sessão no plugin).
"""

from __future__ import annotations

from typing import Any

from .config.settings import get_settings
from .db.store import TokenStore
from .tools import (
    authenticate,
    context_status,
    get_twin_context,
    list_tokens,
    refresh_context,
    register_token,
    revoke_token,
    rotate_token,
    whoami,
)

# Domínio canônico deste plugin — usado no capability/required_scope e como prefixo de
# tool (o agregador descobre o domínio por ``<domain>_<op>``).
DOMAIN = "dev-twin"

# ── Tool Schemas + Policy metadata (STD-MCP-001 CI-2) ─────────────────────────
# Cada tool declara, além de description/schema, os 4 campos de política:
#   capability     — id estável <namespace>.<tool> (não derivar por nome no gateway)
#   required_scope — escopo de execução no formato dominio:tipo:acao (least-privilege)
#   resource_type  — tipo de recurso tocado
#   data_domain    — domínio de dado (governa HITL floor / classificação LGPD)
# inputSchema MUST ser type=object com properties (senão a validação no front-door
# é fail-open). Leituras usam verbo :read; mutações usam :write.
# O dict literal abaixo é byte-a-byte o do server-fonte (capability/required_scope no
# namespace antigo ``dev-twin-mcp``); o loop logo após reescreve SOMENTE esses 2 campos
# para o namespace consolidado (ver docstring do módulo).
# ─────────────────────────────────────────────────────────────────────────────
_TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    # ── Operacional ───────────────────────────────────────────────────────── #
    "status": {
        "description": "Retorna o status real do servidor (nome, versão, nº de tools).",
        "capability": "dev-twin-mcp.status",
        "required_scope": "dev-twin-mcp:status:read",
        "resource_type": "status",
        "data_domain": "operational",
        "schema": {"type": "object", "additionalProperties": False, "properties": {}},
    },
    # ── Auth / sessão ─────────────────────────────────────────────────────── #
    "authenticate": {
        "description": (
            "PRIMEIRA tool por sessão. "
            "Valida TWIN_TOKEN, carrega perfil (nome, role, escopos, ambiente). "
            "Sem authenticate(), whoami() e get_twin_context() falham."
        ),
        "capability": "dev-twin-mcp.authenticate",
        "required_scope": "dev-twin-mcp:session:write",
        "resource_type": "session",
        "data_domain": "identity",
        "schema": {
            "type": "object",
            "properties": {
                "token": {
                    "type": "string",
                    "description": "Token do usuário/agente (TWIN_TOKEN do ambiente).",
                },
            },
            "required": ["token"],
            "additionalProperties": False,
        },
    },
    "whoami": {
        "description": (
            "Retorna o usuário autenticado na sessão: "
            "user_id, name, email, role, scopes, environment, authenticated_at. "
            "Requer authenticate() anterior."
        ),
        "capability": "dev-twin-mcp.whoami",
        "required_scope": "dev-twin-mcp:session:read",
        "resource_type": "session",
        "data_domain": "identity",
        "schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    "get_twin_context": {
        "description": (
            "Contexto completo da sessão: identidade, git/OS/hostname e MCPs disponíveis. "
            "Coleta lazy na primeira chamada (cache 60s)."
        ),
        "capability": "dev-twin-mcp.get_twin_context",
        "required_scope": "dev-twin-mcp:context:read",
        "resource_type": "context",
        "data_domain": "identity",
        "schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    "refresh_context": {
        "description": (
            "Recaptura contexto de ambiente (git branch, cwd) sem invalidar autenticação. "
            "Use após trocar de branch ou diretório."
        ),
        "capability": "dev-twin-mcp.refresh_context",
        "required_scope": "dev-twin-mcp:context:write",
        "resource_type": "context",
        "data_domain": "identity",
        "schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    "context_status": {
        "description": (
            "Retorna métricas de uso do contexto Claude: tool_calls desde autenticação, "
            "tempo decorrido e recomendação de /compact (ok | compact_soon | compact_now). "
            "Use periodicamente para saber quando compactar o contexto e reduzir custo de tokens."
        ),
        "capability": "dev-twin-mcp.context_status",
        "required_scope": "dev-twin-mcp:context:read",
        "resource_type": "context",
        "data_domain": "operational",
        "schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    # ── Admin (gerenciam tokens de acesso) ────────────────────────────────── #
    "register_token": {
        "description": (
            "Admin — Registra usuário e emite token de acesso (exibido uma única vez). "
            "Requer TWIN_ADMIN_TOKEN. Roles: developer | admin | agent | readonly."
        ),
        "capability": "dev-twin-mcp.register_token",
        "required_scope": "dev-twin-mcp:token:write",
        "resource_type": "token",
        "data_domain": "identity",
        "schema": {
            "type": "object",
            "properties": {
                "admin_token": {
                    "type": "string",
                    "description": "Token de admin (TWIN_ADMIN_TOKEN).",
                },
                "name": {"type": "string", "description": "Nome de exibição."},
                "email": {"type": "string", "description": "Email do usuário."},
                "role": {
                    "type": "string",
                    "enum": ["developer", "admin", "agent", "readonly"],
                    "description": "Papel do usuário. Default: developer.",
                    "default": "developer",
                },
                "environment": {
                    "type": "string",
                    "enum": ["dev", "staging", "production"],
                    "description": "Ambiente de atuação. Default: dev.",
                    "default": "dev",
                },
                "scopes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Escopos permitidos. Default: ['*'] (tudo).",
                },
                "expires_in_days": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Validade em dias. Omitir = sem expiração.",
                },
                "tenant_id": {
                    "type": "string",
                    "description": (
                        "Tenant padrão do usuário. Ex: 'tenant_abc123'. "
                        "Quando definido, o config-mcp usa get_session_tenant_config "
                        "para retornar a config deste tenant automaticamente."
                    ),
                },
            },
            "required": ["admin_token", "name", "email"],
            "additionalProperties": False,
        },
    },
    "revoke_token": {
        "description": (
            "Admin — Revoga um token ou todos os tokens de um user_id. "
            "Requer admin_token. O usuário perde acesso imediatamente."
        ),
        "capability": "dev-twin-mcp.revoke_token",
        "required_scope": "dev-twin-mcp:token:write",
        "resource_type": "token",
        "data_domain": "identity",
        "schema": {
            "type": "object",
            "properties": {
                "admin_token": {"type": "string"},
                "identifier": {
                    "type": "string",
                    "description": "Token completo ou user_id a revogar.",
                },
            },
            "required": ["admin_token", "identifier"],
            "additionalProperties": False,
        },
    },
    "rotate_token": {
        "description": (
            "Admin — Revoga o token atual e emite um novo para o mesmo usuário. "
            "Útil para rotação periódica de segurança. "
            "O novo token é exibido uma única vez."
        ),
        "capability": "dev-twin-mcp.rotate_token",
        "required_scope": "dev-twin-mcp:token:write",
        "resource_type": "token",
        "data_domain": "identity",
        "schema": {
            "type": "object",
            "properties": {
                "admin_token": {"type": "string"},
                "identifier": {
                    "type": "string",
                    "description": "Token ou user_id a rotacionar.",
                },
            },
            "required": ["admin_token", "identifier"],
            "additionalProperties": False,
        },
    },
    "list_tokens": {
        "description": (
            "Admin — Lista metadados de usuários/tokens (sem exibir valores). Requer TWIN_ADMIN_TOKEN."
        ),
        "capability": "dev-twin-mcp.list_tokens",
        "required_scope": "dev-twin-mcp:token:read",
        "resource_type": "token",
        "data_domain": "identity",
        "schema": {
            "type": "object",
            "properties": {
                "admin_token": {"type": "string"},
                "include_revoked": {
                    "type": "boolean",
                    "description": "Incluir tokens revogados. Default: false.",
                    "default": False,
                },
            },
            "required": ["admin_token"],
            "additionalProperties": False,
        },
    },
}

# Reescreve capability/required_scope para o namespace do server consolidado (strangler):
#   capability     -> devteam-mcp.<domain>_<op>   (dropa o antigo 'dev-twin-mcp.<op>')
#   required_scope -> <domain>:<recurso>:<ação>   (dropa o antigo prefixo 'dev-twin-mcp:')
# Os DEMAIS campos (resource_type/data_domain/description/schema) ficam byte-a-byte do
# fonte. O split(":", 1)[1] preserva o par <recurso>:<ação> intacto (least-privilege).
for _op, _meta in _TOOL_SCHEMAS.items():
    _meta["capability"] = f"devteam-mcp.{DOMAIN}_{_op}"
    _meta["required_scope"] = f"{DOMAIN}:{_meta['required_scope'].split(':', 1)[1]}"


# ── status (tool operacional) ─────────────────────────────────────────────────


def status() -> dict[str, Any]:
    """Retorna o status real do servidor."""
    return {"status": "ok", "service": "dev-twin-mcp", "tools": len(_TOOL_SCHEMAS)}


# ── Dispatcher (stateful: recebe a Store do domínio construída da sessão) ──────


async def dispatch(name: str, args: dict[str, Any], store: TokenStore) -> dict[str, Any]:
    """Despacha a chamada para a função de tool (async). ``name`` é o nome de op SEM
    prefixo de domínio (o ``plugin.dispatch`` já o retirou). O tenant NÃO viaja nos args
    (INV-3): o ``store`` já está ligado ao pool do tenant (resolvido dos claims do inner
    token). As tools de sessão em memória / status IGNORAM o ``store``."""
    # ── Operacional / sessão em memória (não tocam o banco) ───────────────── #
    if name == "status":
        return status()
    if name == "whoami":
        return whoami()
    if name == "get_twin_context":
        return get_twin_context()
    if name == "refresh_context":
        return refresh_context()
    if name == "context_status":
        return context_status()
    # ── Tocam o banco (agent_tokens) — store tenant-scoped ────────────────── #
    settings = get_settings()
    if name == "authenticate":
        return await authenticate(store, token=args["token"])
    if name == "register_token":
        return await register_token(
            store,
            admin_token_configured=settings.admin_token,
            admin_token=args["admin_token"],
            name=args["name"],
            email=args["email"],
            role=args.get("role", "developer"),
            environment=args.get("environment", "dev"),
            scopes=args.get("scopes"),
            expires_in_days=args.get("expires_in_days"),
            tenant_id=args.get("tenant_id"),
        )
    if name == "revoke_token":
        return await revoke_token(
            store,
            admin_token_configured=settings.admin_token,
            admin_token=args["admin_token"],
            identifier=args["identifier"],
        )
    if name == "rotate_token":
        return await rotate_token(
            store,
            admin_token_configured=settings.admin_token,
            admin_token=args["admin_token"],
            identifier=args["identifier"],
        )
    if name == "list_tokens":
        return await list_tokens(
            store,
            admin_token_configured=settings.admin_token,
            admin_token=args["admin_token"],
            include_revoked=args.get("include_revoked", False),
        )
    raise KeyError(name)
