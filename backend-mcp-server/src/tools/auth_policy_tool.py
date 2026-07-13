"""Tools de Política de Auth — upsert por recurso (chave natural única `resource`).

O agente define a política (tipo de auth, papéis, sensibilidade, regras);
`save_auth_policy` persiste/atualiza a política do recurso (upsert). Uma política por
recurso — re-chamar sobrescreve. Thin wrappers sobre o `BackendStore`."""

from __future__ import annotations

from typing import Any

from ..db.store import BackendStore


async def save_auth_policy(
    store: BackendStore,
    resource: str,
    auth_type: str,
    roles: Any = None,
    data_sensitivity: str | None = None,
    rules: Any = None,
    status: str | None = None,
) -> dict[str, Any]:
    policy = await store.save_auth_policy(
        resource=resource,
        auth_type=auth_type,
        roles=roles,
        data_sensitivity=data_sensitivity,
        rules=rules,
        status=status,
    )
    return {"saved": True, "auth_policy": policy}


async def list_auth_policies(
    store: BackendStore, auth_type: str | None = None, status: str | None = None
) -> dict[str, Any]:
    policies = await store.list_auth_policies(auth_type=auth_type, status=status)
    return {
        "total": len(policies),
        "filters": {"auth_type": auth_type, "status": status},
        "auth_policies": policies,
    }


async def get_auth_policy(store: BackendStore, resource: str) -> dict[str, Any]:
    policy = await store.get_auth_policy(resource)
    if policy is None:
        return {"error": "not_found", "resource": resource}
    return policy


async def delete_auth_policy(store: BackendStore, resource: str) -> dict[str, Any]:
    deleted = await store.delete_auth_policy(resource)
    return {"deleted": deleted > 0, "resource": resource, "deleted_count": deleted}
