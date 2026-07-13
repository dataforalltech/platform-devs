"""Tools de Environment — upsert por nome (chave natural única `name`).

O agente registra ambientes/clusters de deploy; `set_environment` persiste/atualiza o
ambiente (upsert). Um registro por `name` — re-chamar sobrescreve. Thin wrappers sobre
o `DevopsStore`."""

from __future__ import annotations

from typing import Any

from ..db.store import DevopsStore

VALID_KINDS = frozenset({"kubernetes", "vm", "serverless", "docker", "bare_metal"})


async def set_environment(
    store: DevopsStore,
    name: str,
    kind: str,
    region: str | None = None,
    config: Any = None,
    status: str | None = None,
) -> dict[str, Any]:
    if kind not in VALID_KINDS:
        return {"error": "invalid_kind", "kind": kind, "valid": sorted(VALID_KINDS)}
    environment = await store.set_environment(
        name=name, kind=kind, region=region, config=config, status=status
    )
    return {"saved": True, "environment": environment}


async def list_environments(
    store: DevopsStore, kind: str | None = None, status: str | None = None
) -> dict[str, Any]:
    environments = await store.list_environments(kind=kind, status=status)
    return {
        "total": len(environments),
        "filters": {"kind": kind, "status": status},
        "environments": environments,
    }


async def get_environment(store: DevopsStore, name: str) -> dict[str, Any]:
    environment = await store.get_environment(name)
    if environment is None:
        return {"error": "not_found", "name": name}
    return environment


async def delete_environment(store: DevopsStore, name: str) -> dict[str, Any]:
    deleted = await store.delete_environment(name)
    return {"deleted": deleted > 0, "name": name, "deleted_count": deleted}
