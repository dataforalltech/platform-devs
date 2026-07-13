"""Tools de Product Vision — upsert por produto (chave natural única `product`).

O agente redige a visão/missão/objetivos; `set_product_vision` persiste/atualiza a
visão do produto (upsert). Uma visão por produto — re-chamar sobrescreve. Thin
wrappers sobre o `ProductOwnerStore`."""

from __future__ import annotations

from typing import Any

from ..db.store import ProductOwnerStore


async def set_product_vision(
    store: ProductOwnerStore,
    product: str,
    vision: str | None = None,
    target_audience: str | None = None,
    content: Any = None,
    status: str | None = None,
) -> dict[str, Any]:
    result = await store.set_product_vision(
        product=product,
        vision=vision,
        target_audience=target_audience,
        content=content,
        status=status,
    )
    return {"saved": True, "product_vision": result}


async def list_product_visions(store: ProductOwnerStore, status: str | None = None) -> dict[str, Any]:
    visions = await store.list_product_visions(status=status)
    return {"total": len(visions), "filters": {"status": status}, "product_visions": visions}


async def get_product_vision(store: ProductOwnerStore, product: str) -> dict[str, Any]:
    vision = await store.get_product_vision(product)
    if vision is None:
        return {"error": "not_found", "product": product}
    return vision


async def delete_product_vision(store: ProductOwnerStore, product: str) -> dict[str, Any]:
    deleted = await store.delete_product_vision(product)
    return {"deleted": deleted > 0, "product": product, "deleted_count": deleted}
