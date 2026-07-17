"""Tools de Feature Spec — CRUD que persiste a spec fornecida pelo agente chamador.

O agente gera o conteúdo (user stories/acceptance criteria/objetivo); estas tools
persistem no banco do tenant e devolvem o registro com `id`. Thin wrappers sobre o
`ProductManagerStore` (validação leve + envelope de resposta)."""

from __future__ import annotations

from typing import Any

from ..db.store import ProductManagerStore


async def save_feature_spec(
    store: ProductManagerStore,
    feature: str,
    content: Any,
    objective: str | None = None,
    priority: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    spec = await store.save_feature_spec(
        feature=feature, content=content, objective=objective, priority=priority, status=status
    )
    return {"saved": True, "feature_spec": spec}


async def list_feature_specs(
    store: ProductManagerStore, feature: str | None = None, status: str | None = None
) -> dict[str, Any]:
    specs = await store.list_feature_specs(feature=feature, status=status)
    return {"total": len(specs), "filters": {"feature": feature, "status": status}, "feature_specs": specs}


async def get_feature_spec(store: ProductManagerStore, spec_id: int) -> dict[str, Any]:
    spec = await store.get_feature_spec(spec_id)
    if spec is None:
        return {"error": "not_found", "id": spec_id}
    return spec


async def update_feature_spec(
    store: ProductManagerStore,
    spec_id: int,
    objective: str | None = None,
    priority: str | None = None,
    content: Any = None,
    status: str | None = None,
) -> dict[str, Any]:
    spec = await store.update_feature_spec(
        spec_id, objective=objective, priority=priority, content=content, status=status
    )
    if spec is None:
        return {"error": "not_found", "id": spec_id}
    return {"updated": True, "feature_spec": spec}


async def delete_feature_spec(store: ProductManagerStore, spec_id: int) -> dict[str, Any]:
    deleted = await store.delete_feature_spec(spec_id)
    return {"deleted": deleted > 0, "id": spec_id, "deleted_count": deleted}
