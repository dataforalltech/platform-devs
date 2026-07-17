"""Tools de Security Control — upsert por chave natural única `(system_name, control_key)`.

O agente define o controle de segurança (nome, tipo, referência de framework, detalhes);
`set_security_control` persiste/atualiza o controle do sistema (upsert). Um controle por
`(system_name, control_key)` — re-chamar sobrescreve. Thin wrappers sobre o `SecurityStore`."""

from __future__ import annotations

from typing import Any

from ..db.store import SecurityStore


async def set_security_control(
    store: SecurityStore,
    system_name: str,
    control_key: str,
    name: str | None = None,
    control_type: str | None = None,
    framework_ref: str | None = None,
    details: Any = None,
    status: str | None = None,
) -> dict[str, Any]:
    control = await store.set_security_control(
        system_name=system_name,
        control_key=control_key,
        name=name,
        control_type=control_type,
        framework_ref=framework_ref,
        details=details,
        status=status,
    )
    return {"saved": True, "security_control": control}


async def list_security_controls(
    store: SecurityStore, system_name: str | None = None, status: str | None = None
) -> dict[str, Any]:
    controls = await store.list_security_controls(system_name=system_name, status=status)
    return {
        "total": len(controls),
        "filters": {"system_name": system_name, "status": status},
        "security_controls": controls,
    }


async def get_security_control(store: SecurityStore, system_name: str, control_key: str) -> dict[str, Any]:
    control = await store.get_security_control(system_name, control_key)
    if control is None:
        return {"error": "not_found", "system_name": system_name, "control_key": control_key}
    return control


async def delete_security_control(store: SecurityStore, system_name: str, control_key: str) -> dict[str, Any]:
    deleted = await store.delete_security_control(system_name, control_key)
    return {
        "deleted": deleted > 0,
        "system_name": system_name,
        "control_key": control_key,
        "deleted_count": deleted,
    }
