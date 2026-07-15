"""Tools de Página Next.js — upsert por rota (chave natural única `route`).

O agente gera o código-fonte da página; `set_page` persiste/atualiza a página da
rota (upsert). Uma página por rota — re-chamar sobrescreve. Thin wrappers sobre o
`FrontendStore`."""

from __future__ import annotations

from typing import Any

from ..db.store import FrontendStore


async def set_page(
    store: FrontendStore,
    route: str,
    title: str | None = None,
    framework: str | None = None,
    page_type: str | None = None,
    code: str | None = None,
    meta: Any = None,
    status: str | None = None,
) -> dict[str, Any]:
    page = await store.set_page(
        route=route,
        title=title,
        framework=framework,
        page_type=page_type,
        code=code,
        meta=meta,
        status=status,
    )
    return {"saved": True, "page": page}


async def list_pages(
    store: FrontendStore, framework: str | None = None, status: str | None = None
) -> dict[str, Any]:
    pages = await store.list_pages(framework=framework, status=status)
    return {
        "total": len(pages),
        "filters": {"framework": framework, "status": status},
        "pages": pages,
    }


async def get_page(store: FrontendStore, route: str) -> dict[str, Any]:
    page = await store.get_page(route)
    if page is None:
        return {"error": "not_found", "route": route}
    return page


async def delete_page(store: FrontendStore, route: str) -> dict[str, Any]:
    deleted = await store.delete_page(route)
    return {"deleted": deleted > 0, "route": route, "deleted_count": deleted}
