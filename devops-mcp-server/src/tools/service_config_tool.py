"""Tools de Service Config — upsert por serviço (chave natural única `service`).

O agente define os defaults de devops de um serviço (réplicas/recursos/env);
`set_service_config` persiste/atualiza a config do serviço (upsert). Uma config por
serviço — re-chamar sobrescreve. Thin wrappers sobre o `DevopsStore`."""

from __future__ import annotations

from typing import Any

from ..db.store import DevopsStore


async def set_service_config(
    store: DevopsStore, service: str, settings: Any, status: str | None = None
) -> dict[str, Any]:
    config = await store.set_service_config(service=service, settings=settings, status=status)
    return {"saved": True, "service_config": config}


async def list_service_configs(store: DevopsStore, status: str | None = None) -> dict[str, Any]:
    configs = await store.list_service_configs(status=status)
    return {"total": len(configs), "filters": {"status": status}, "service_configs": configs}


async def get_service_config(store: DevopsStore, service: str) -> dict[str, Any]:
    config = await store.get_service_config(service)
    if config is None:
        return {"error": "not_found", "service": service}
    return config


async def delete_service_config(store: DevopsStore, service: str) -> dict[str, Any]:
    deleted = await store.delete_service_config(service)
    return {"deleted": deleted > 0, "service": service, "deleted_count": deleted}
