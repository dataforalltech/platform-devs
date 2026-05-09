"""Ferramentas de gestão de configurações por tenant.

Namespace: tenants.<tenant_id>
"""
from __future__ import annotations

from typing import Any

from ..knowledge.store import ConfigStore


def _get_twin_tenant_id() -> str | None:
    """Tenta resolver o tenant_id da sessão atual via agent-twin-mcp HTTP API."""
    try:
        from shared.twin_client import TwinClient
        return TwinClient.from_env().get_tenant_id()
    except Exception:  # noqa: BLE001
        return None


def get_tenant_config(
    store: ConfigStore,
    tenant_id: str,
    key_pattern: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Retorna variáveis de configuração de um tenant.

    Args:
        tenant_id: Identificador do tenant. Ex: 'tenant_abc123'.
        key_pattern: Filtro substring no nome das variáveis. Ex: 'DATABASE'.
        limit: Máximo de variáveis retornadas. Padrão: 50.
    """
    ns = f"tenants.{tenant_id}"
    config = store.get_namespace(ns)
    if not config:
        return {"found": False, "tenant_id": tenant_id}
    if key_pattern:
        config = {k: v for k, v in config.items() if key_pattern.upper() in k.upper()}
    if len(config) > limit:
        config = dict(list(config.items())[:limit])
    return {"found": True, "tenant_id": tenant_id, "config": config, "count": len(config)}


def set_tenant_config(
    store: ConfigStore,
    tenant_id: str,
    key: str,
    value: str,
) -> dict[str, Any]:
    """Define uma variável de configuração para um tenant."""
    store.set(f"tenants.{tenant_id}", key, value)
    return {"success": True, "tenant_id": tenant_id, "key": key}


def get_session_tenant_config(store: ConfigStore) -> dict[str, Any]:
    """Retorna a config do tenant associado à sessão autenticada no agent-twin-mcp.

    Resolve automaticamente o tenant_id via HTTP API do agent-twin (:7098).
    Não requer que o chamador saiba o tenant_id.
    """
    tenant_id = _get_twin_tenant_id()
    if not tenant_id:
        return {
            "found": False,
            "error": "no_tenant_in_session",
            "hint": (
                "Nenhum tenant_id na sessão. Verifique: (1) agent-twin-mcp em :7098, "
                "(2) authenticate() chamado, (3) tenant_id configurado no perfil."
            ),
        }
    return get_tenant_config(store, tenant_id)


def list_tenants(store: ConfigStore) -> dict[str, Any]:
    """Lista todos os tenants configurados e a quantidade de variáveis de cada um."""
    tenants: dict[str, int] = {}
    for ns in store.list_namespaces():
        if ns.startswith("tenants."):
            tid = ns.removeprefix("tenants.")
            tenants[tid] = len(store.list_keys(ns).get(ns, []))
    return {"tenants": tenants, "count": len(tenants)}
