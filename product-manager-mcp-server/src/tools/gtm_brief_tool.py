"""Tools de GTM Brief — CRUD que persiste o brief fornecido pelo agente chamador.

O agente gera o conteúdo (segmentos-alvo/mensagens-chave/canais/métricas); estas
tools persistem no banco do tenant e devolvem o registro com `id`. Thin wrappers
sobre o `ProductManagerStore`."""

from __future__ import annotations

from typing import Any

from ..db.store import ProductManagerStore


async def save_gtm_brief(
    store: ProductManagerStore,
    product: str,
    content: Any,
    launch_timing: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    brief = await store.save_gtm_brief(
        product=product, content=content, launch_timing=launch_timing, status=status
    )
    return {"saved": True, "gtm_brief": brief}


async def list_gtm_briefs(
    store: ProductManagerStore, product: str | None = None, status: str | None = None
) -> dict[str, Any]:
    briefs = await store.list_gtm_briefs(product=product, status=status)
    return {"total": len(briefs), "filters": {"product": product, "status": status}, "gtm_briefs": briefs}


async def get_gtm_brief(store: ProductManagerStore, brief_id: int) -> dict[str, Any]:
    brief = await store.get_gtm_brief(brief_id)
    if brief is None:
        return {"error": "not_found", "id": brief_id}
    return brief


async def update_gtm_brief(
    store: ProductManagerStore,
    brief_id: int,
    launch_timing: str | None = None,
    content: Any = None,
    status: str | None = None,
) -> dict[str, Any]:
    brief = await store.update_gtm_brief(
        brief_id, launch_timing=launch_timing, content=content, status=status
    )
    if brief is None:
        return {"error": "not_found", "id": brief_id}
    return {"updated": True, "gtm_brief": brief}


async def delete_gtm_brief(store: ProductManagerStore, brief_id: int) -> dict[str, Any]:
    deleted = await store.delete_gtm_brief(brief_id)
    return {"deleted": deleted > 0, "id": brief_id, "deleted_count": deleted}
