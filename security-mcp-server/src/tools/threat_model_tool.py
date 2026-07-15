"""Tools de Threat Model — CRUD que persiste o modelo fornecido pelo agente chamador.

O agente gera o conteúdo (componentes, ameaças STRIDE/PASTA, sumário); estas tools
persistem no banco do tenant e devolvem o registro com `id`. Thin wrappers sobre o
`SecurityStore` (validação leve + envelope de resposta)."""

from __future__ import annotations

from typing import Any

from ..db.store import SecurityStore


async def save_threat_model(
    store: SecurityStore,
    system_name: str,
    methodology: str = "STRIDE",
    title: str | None = None,
    components: Any = None,
    threats: Any = None,
    summary: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    model = await store.save_threat_model(
        system_name=system_name,
        methodology=methodology,
        title=title,
        components=components,
        threats=threats,
        summary=summary,
        status=status,
    )
    return {"saved": True, "threat_model": model}


async def list_threat_models(
    store: SecurityStore, system_name: str | None = None, status: str | None = None
) -> dict[str, Any]:
    models = await store.list_threat_models(system_name=system_name, status=status)
    return {
        "total": len(models),
        "filters": {"system_name": system_name, "status": status},
        "threat_models": models,
    }


async def get_threat_model(store: SecurityStore, model_id: int) -> dict[str, Any]:
    model = await store.get_threat_model(model_id)
    if model is None:
        return {"error": "not_found", "id": model_id}
    return model


async def update_threat_model(
    store: SecurityStore,
    model_id: int,
    methodology: str | None = None,
    title: str | None = None,
    components: Any = None,
    threats: Any = None,
    summary: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    model = await store.update_threat_model(
        model_id,
        methodology=methodology,
        title=title,
        components=components,
        threats=threats,
        summary=summary,
        status=status,
    )
    if model is None:
        return {"error": "not_found", "id": model_id}
    return {"updated": True, "threat_model": model}


async def delete_threat_model(store: SecurityStore, model_id: int) -> dict[str, Any]:
    deleted = await store.delete_threat_model(model_id)
    return {"deleted": deleted > 0, "id": model_id, "deleted_count": deleted}
