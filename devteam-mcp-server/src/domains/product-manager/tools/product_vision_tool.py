"""Tools de Product Vision — upsert por produto (chave natural única `product`).

O agente define a visão/missão/objetivos do produto; `set_product_vision` persiste/
atualiza a visão do produto (upsert). Uma visão por produto — re-chamar sobrescreve.
Thin wrappers sobre o `ProductManagerStore`."""

from __future__ import annotations

from typing import Any

from ..db.store import ProductManagerStore


async def set_product_vision(
    store: ProductManagerStore,
    product: str,
    vision: str | None = None,
    mission: str | None = None,
    goals: Any = None,
    status: str | None = None,
) -> dict[str, Any]:
    vis = await store.set_product_vision(
        product=product, vision=vision, mission=mission, goals=goals, status=status
    )
    return {"saved": True, "product_vision": vis}


async def list_product_visions(store: ProductManagerStore, status: str | None = None) -> dict[str, Any]:
    visions = await store.list_product_visions(status=status)
    return {"total": len(visions), "filters": {"status": status}, "product_visions": visions}


async def get_product_vision(store: ProductManagerStore, product: str) -> dict[str, Any]:
    vis = await store.get_product_vision(product)
    if vis is None:
        return {"error": "not_found", "product": product}
    return vis


async def delete_product_vision(store: ProductManagerStore, product: str) -> dict[str, Any]:
    deleted = await store.delete_product_vision(product)
    return {"deleted": deleted > 0, "product": product, "deleted_count": deleted}
