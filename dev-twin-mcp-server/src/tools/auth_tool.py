"""Ferramentas de autenticação e contexto de sessão.

authenticate     — valida token, carrega perfil, registra sessão (~100ms, sem coletar contexto)
whoami           — retorna usuário autenticado na sessão atual
get_twin_context — contexto completo: usuário + ambiente (lazy, cached 60s)
refresh_context  — força re-coleta do contexto de ambiente
context_status   — retorna métricas de uso do contexto e recomendação de /compact
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

try:
    from shared.config_client import ConfigClient
    _has_config_client = True
except ImportError:
    _has_config_client = False

_log = logging.getLogger(__name__)

_CRITICAL_PREFIXES = ("JWT_", "URL_")
_CRITICAL_EXACT = {"INTERNAL_API_TOKEN", "SERVICE_ID"}

from ..knowledge.session import (
    SessionManager,
    UserSession,
    collect_environment_context,
)
from ..db.token_store import TokenStore

# Thresholds para recomendação de /compact
_COMPACT_WARN_CALLS = 80   # aviso
_COMPACT_URGE_CALLS = 150  # recomendação forte


def authenticate(store: TokenStore, token: str) -> dict[str, Any]:
    """Autentica o usuário/agente e inicializa a sessão.

    PRIMEIRA TOOL A SER CHAMADA em toda sessão. Valida o token contra
    a tabela de tokens e carrega o perfil do usuário.

    Contexto de ambiente (git, OS) é coletado de forma lazy em get_twin_context()
    — authenticate() retorna em ~100ms sem bloquear.

    Args:
        token: Token do usuário/agente (TWIN_TOKEN do ambiente).
    """
    record = store.validate(token)
    if not record:
        return {
            "authenticated": False,
            "error": (
                "Token inválido, expirado ou revogado. "
                "Verifique TWIN_TOKEN ou solicite um novo token ao admin."
            ),
        }

    session = UserSession(
        token=token,
        user_id=record["user_id"],
        name=record["name"],
        email=record["email"],
        role=record["role"],
        scopes=record["scopes"] if isinstance(record["scopes"], list) else json.loads(record["scopes"]),
        environment=record["environment"],
        tenant_id=record.get("tenant_id"),
        authenticated_at=datetime.now(timezone.utc).isoformat(),
        context={},  # contexto coletado de forma lazy em get_twin_context()
    )
    SessionManager.set(session)
    store.touch(record["user_id"])

    # --- Load env config from config-mcp (non-blocking) ---
    env_config_loaded = False
    env_vars_count = 0
    if _has_config_client:
        try:
            client = ConfigClient.from_env()
            all_vars = client.get_env_config(session.environment)
            if all_vars:
                critical_vars = {
                    k: v
                    for k, v in all_vars.items()
                    if any(k.startswith(p) for p in _CRITICAL_PREFIXES)
                    or k in _CRITICAL_EXACT
                }
                SessionManager.update_context({"env_config": critical_vars})
                env_config_loaded = True
                env_vars_count = len(critical_vars)
        except Exception as exc:  # noqa: BLE001
            _log.warning("config_mcp_unavailable: %s", exc)

    return {
        "authenticated": True,
        "user_id": session.user_id,
        "name": session.name,
        "role": session.role,
        "environment": session.environment,
        "tenant_id": session.tenant_id,
        "env_config_loaded": env_config_loaded,
        "env_vars_count": env_vars_count,
        "active_env_namespace": f"env.{session.environment}",
        "message": (
            f"Bem-vindo, {session.name}! "
            "Use get_twin_context() para contexto completo (git, OS)."
        ),
    }


def whoami() -> dict[str, Any]:
    """Retorna o usuário autenticado na sessão atual.

    Útil para verificar identidade a qualquer momento durante a sessão.
    Retorna erro se authenticate() ainda não foi chamado.
    """
    session = SessionManager.get()
    if not session:
        return {
            "authenticated": False,
            "error": "Nenhuma sessão ativa. Chame authenticate(token) primeiro.",
        }
    return {
        "authenticated": True,
        "user_id": session.user_id,
        "name": session.name,
        "email": session.email,
        "role": session.role,
        "scopes": session.scopes,
        "environment": session.environment,
        "tenant_id": session.tenant_id,
        "authenticated_at": session.authenticated_at,
    }


def get_twin_context() -> dict[str, Any]:
    """Retorna o contexto completo da sessão: usuário + ambiente.

    Contexto de ambiente (git, OS) é coletado na primeira chamada e
    cacheado por 60s. Não repete subprocessos git desnecessariamente.
    """
    session = SessionManager.get()
    if not session:
        return {
            "authenticated": False,
            "error": "Nenhuma sessão ativa. Chame authenticate(token) primeiro.",
        }

    # Coleta contexto de forma lazy se ainda não foi coletado
    if not session.context:
        context = collect_environment_context()
        SessionManager.update_context(context)
        session = SessionManager.get()  # re-fetch após update

    tenant_namespaces = [f"tenants.{session.tenant_id}"] if session.tenant_id else []
    return {
        "authenticated": True,
        "user": {
            "user_id": session.user_id,
            "name": session.name,
            "email": session.email,
            "role": session.role,
            "scopes": session.scopes,
            "environment": session.environment,
            "tenant_id": session.tenant_id,
        },
        "context": session.context,
        "authenticated_at": session.authenticated_at,
        "credential_namespaces": [
            f"credentials.{session.user_id}",
            "credentials.acr",
            "credentials.github",
            f"env.{session.environment}",
        ],
        "tenant_namespaces": tenant_namespaces,
    }


def context_status() -> dict[str, Any]:
    """Retorna métricas de uso do contexto e recomendação de /compact.

    Monitora tool_calls desde a autenticação e o tempo decorrido de sessão
    para indicar quando o contexto Claude deve ser compactado via /compact.
    """
    session = SessionManager.get()
    if not session:
        return {
            "authenticated": False,
            "error": "Nenhuma sessão ativa. Chame authenticate(token) primeiro.",
        }

    now = datetime.now(timezone.utc)
    authenticated_at = datetime.fromisoformat(session.authenticated_at)
    elapsed_minutes = (now - authenticated_at).total_seconds() / 60
    tool_calls = session.tool_calls

    if tool_calls >= _COMPACT_URGE_CALLS:
        recommendation = "compact_now"
        message = (
            f"Contexto muito extenso ({tool_calls} tool calls, {elapsed_minutes:.0f}min). "
            "Execute /compact imediatamente para reduzir custo de tokens."
        )
    elif tool_calls >= _COMPACT_WARN_CALLS:
        recommendation = "compact_soon"
        message = (
            f"Contexto crescendo ({tool_calls} tool calls, {elapsed_minutes:.0f}min). "
            "Considere executar /compact em breve."
        )
    else:
        recommendation = "ok"
        message = f"Contexto saudável ({tool_calls} tool calls, {elapsed_minutes:.0f}min)."

    return {
        "authenticated": True,
        "user_id": session.user_id,
        "tool_calls": tool_calls,
        "elapsed_minutes": round(elapsed_minutes, 1),
        "authenticated_at": session.authenticated_at,
        "recommendation": recommendation,
        "compact_warn_threshold": _COMPACT_WARN_CALLS,
        "compact_urge_threshold": _COMPACT_URGE_CALLS,
        "message": message,
    }


def refresh_context() -> dict[str, Any]:
    """Força re-coleta do contexto de ambiente (git branch, cwd).

    Use após mudar de diretório, trocar de branch ou iniciar novos serviços.
    Ignora o cache de 60s e captura o estado atual.
    """
    session = SessionManager.get()
    if not session:
        return {
            "success": False,
            "error": "Nenhuma sessão ativa. Chame authenticate(token) primeiro.",
        }
    new_context = collect_environment_context(force=True)
    SessionManager.update_context(new_context)
    return {
        "success": True,
        "user_id": session.user_id,
        "context": new_context,
    }
