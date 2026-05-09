"""Ferramentas administrativas de gestão de tokens.

Requerem TWIN_ADMIN_TOKEN configurado e correspondência no argumento admin_token.

register_token — cria novo usuário/token
revoke_token   — revoga acesso
rotate_token   — revoga + emite novo token para o mesmo usuário
list_tokens    — lista todos os tokens ativos (sem exibir os valores)
"""
from __future__ import annotations

import secrets
from typing import Any

from ..knowledge.token_store import TokenStore


def _check_admin(admin_token: str, provided: str) -> dict[str, Any] | None:
    """Retorna erro se admin_token não confere (timing-safe). Retorna None se OK."""
    if not admin_token:
        return {
            "error": "AdminNotConfigured",
            "details": "TWIN_ADMIN_TOKEN não está configurado. Defina-o no .env.",
        }
    if not secrets.compare_digest(provided, admin_token):
        return {"error": "Unauthorized", "details": "admin_token incorreto."}
    return None


def register_token(
    store: TokenStore,
    admin_token_configured: str,
    admin_token: str,
    name: str,
    email: str,
    role: str = "developer",
    environment: str = "dev",
    scopes: list[str] | None = None,
    expires_in_days: int | None = None,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    """Registra um novo usuário/agente e emite seu token de acesso."""
    if err := _check_admin(admin_token_configured, admin_token):
        return err

    record = store.register(
        name=name,
        email=email,
        role=role,
        environment=environment,
        scopes=scopes,
        expires_in_days=expires_in_days,
        tenant_id=tenant_id,
    )
    return {
        "success": True,
        "user_id": record["user_id"],
        "token": record["token"],
        "role": record["role"],
        "scopes": record["scopes"],
        "environment": record["environment"],
        "tenant_id": record["tenant_id"],
        "expires_at": record["expires_at"],
        "warning": "Armazene este token com segurança — não será exibido novamente.",
    }


def revoke_token(
    store: TokenStore,
    admin_token_configured: str,
    admin_token: str,
    identifier: str,
) -> dict[str, Any]:
    """Revoga um token ou todos os tokens de um user_id."""
    if err := _check_admin(admin_token_configured, admin_token):
        return err

    result = store.revoke(identifier)
    return {
        "success": result["revoked"],
        "identifier": identifier,
        "affected": result["affected"],
    }


def rotate_token(
    store: TokenStore,
    admin_token_configured: str,
    admin_token: str,
    identifier: str,
) -> dict[str, Any]:
    """Revoga o token atual e emite um novo para o mesmo usuário (user_id)."""
    if err := _check_admin(admin_token_configured, admin_token):
        return err

    try:
        record = store.rotate(identifier)
        return {
            "success": True,
            "new_token": record["token"],
            "user_id": record["user_id"],
            "name": record["name"],
            "warning": "Armazene o novo token com segurança — não será exibido novamente.",
        }
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": str(exc)}


def list_tokens(
    store: TokenStore,
    admin_token_configured: str,
    admin_token: str,
    include_revoked: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    """Lista tokens registrados (sem exibir valores dos tokens)."""
    if err := _check_admin(admin_token_configured, admin_token):
        return err

    records = store.list_all(include_revoked=include_revoked, limit=limit, offset=offset)
    return {"tokens": records, "count": len(records)}
