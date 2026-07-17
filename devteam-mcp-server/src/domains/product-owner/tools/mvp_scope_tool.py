"""Tools de MVP Scope — upsert por produto (chave natural única `product`).

O agente define o recorte do MVP (core/should/could/out-of-scope); `set_mvp_scope`
persiste/atualiza o escopo do produto (upsert). Um escopo por produto — re-chamar
sobrescreve. Thin wrappers sobre o `ProductOwnerStore`."""

from __future__ import annotations

from typing import Any

from ..db.store import ProductOwnerStore


async def set_mvp_scope(
    store: ProductOwnerStore,
    product: str,
    content: Any,
    goal: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    scope = await store.set_mvp_scope(product=product, content=content, goal=goal, status=status)
    return {"saved": True, "mvp_scope": scope}


async def list_mvp_scopes(store: ProductOwnerStore, status: str | None = None) -> dict[str, Any]:
    scopes = await store.list_mvp_scopes(status=status)
    return {"total": len(scopes), "filters": {"status": status}, "mvp_scopes": scopes}


async def get_mvp_scope(store: ProductOwnerStore, product: str) -> dict[str, Any]:
    scope = await store.get_mvp_scope(product)
    if scope is None:
        return {"error": "not_found", "product": product}
    return scope


async def delete_mvp_scope(store: ProductOwnerStore, product: str) -> dict[str, Any]:
    deleted = await store.delete_mvp_scope(product)
    return {"deleted": deleted > 0, "product": product, "deleted_count": deleted}
