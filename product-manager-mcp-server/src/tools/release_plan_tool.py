"""Tools de Release Plan — CRUD que persiste o plano fornecido pelo agente chamador.

O agente gera o conteúdo (fases/cronograma/features por fase); estas tools persistem
no banco do tenant e devolvem o registro com `id`. Thin wrappers sobre o
`ProductManagerStore`."""

from __future__ import annotations

from typing import Any

from ..db.store import ProductManagerStore


async def save_release_plan(
    store: ProductManagerStore,
    product: str,
    content: Any,
    status: str | None = None,
) -> dict[str, Any]:
    plan = await store.save_release_plan(product=product, content=content, status=status)
    return {"saved": True, "release_plan": plan}


async def list_release_plans(
    store: ProductManagerStore, product: str | None = None, status: str | None = None
) -> dict[str, Any]:
    plans = await store.list_release_plans(product=product, status=status)
    return {"total": len(plans), "filters": {"product": product, "status": status}, "release_plans": plans}


async def get_release_plan(store: ProductManagerStore, plan_id: int) -> dict[str, Any]:
    plan = await store.get_release_plan(plan_id)
    if plan is None:
        return {"error": "not_found", "id": plan_id}
    return plan


async def update_release_plan(
    store: ProductManagerStore,
    plan_id: int,
    content: Any = None,
    status: str | None = None,
) -> dict[str, Any]:
    plan = await store.update_release_plan(plan_id, content=content, status=status)
    if plan is None:
        return {"error": "not_found", "id": plan_id}
    return {"updated": True, "release_plan": plan}


async def delete_release_plan(store: ProductManagerStore, plan_id: int) -> dict[str, Any]:
    deleted = await store.delete_release_plan(plan_id)
    return {"deleted": deleted > 0, "id": plan_id, "deleted_count": deleted}
