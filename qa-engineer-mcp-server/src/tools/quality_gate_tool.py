"""Tools de Quality Gate — upsert por serviço (chave natural única `service`).

O agente define os thresholds do gate de CI; `set_quality_gate` persiste/atualiza o
gate do serviço (upsert). Um gate por serviço — re-chamar sobrescreve. Thin wrappers
sobre o `QAEngineerStore`."""

from __future__ import annotations

from typing import Any

from ..db.store import QAEngineerStore


async def set_quality_gate(
    store: QAEngineerStore, service: str, thresholds: Any, status: str | None = None
) -> dict[str, Any]:
    gate = await store.set_quality_gate(service=service, thresholds=thresholds, status=status)
    return {"saved": True, "quality_gate": gate}


async def list_quality_gates(store: QAEngineerStore, status: str | None = None) -> dict[str, Any]:
    gates = await store.list_quality_gates(status=status)
    return {"total": len(gates), "filters": {"status": status}, "quality_gates": gates}


async def get_quality_gate(store: QAEngineerStore, service: str) -> dict[str, Any]:
    gate = await store.get_quality_gate(service)
    if gate is None:
        return {"error": "not_found", "service": service}
    return gate


async def delete_quality_gate(store: QAEngineerStore, service: str) -> dict[str, Any]:
    deleted = await store.delete_quality_gate(service)
    return {"deleted": deleted > 0, "service": service, "deleted_count": deleted}
