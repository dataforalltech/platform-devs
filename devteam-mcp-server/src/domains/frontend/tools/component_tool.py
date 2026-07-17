"""Tools de Componente React — CRUD que persiste o componente fornecido pelo agente.

O agente gera o código-fonte (JSX/TSX) e os props; estas tools persistem no banco do
tenant e devolvem o registro com `id`. Thin wrappers sobre o `FrontendStore`
(validação leve + envelope de resposta)."""

from __future__ import annotations

from typing import Any

from ..db.store import FrontendStore


async def save_component(
    store: FrontendStore,
    name: str,
    variant: str = "functional",
    framework: str | None = None,
    styling: str | None = None,
    props: Any = None,
    code: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    component = await store.save_component(
        name=name,
        variant=variant,
        framework=framework,
        styling=styling,
        props=props,
        code=code,
        status=status,
    )
    return {"saved": True, "component": component}


async def list_components(
    store: FrontendStore,
    name: str | None = None,
    framework: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    components = await store.list_components(name=name, framework=framework, status=status)
    return {
        "total": len(components),
        "filters": {"name": name, "framework": framework, "status": status},
        "components": components,
    }


async def get_component(store: FrontendStore, component_id: int) -> dict[str, Any]:
    component = await store.get_component(component_id)
    if component is None:
        return {"error": "not_found", "id": component_id}
    return component


async def update_component(
    store: FrontendStore,
    component_id: int,
    variant: str | None = None,
    framework: str | None = None,
    styling: str | None = None,
    props: Any = None,
    code: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    component = await store.update_component(
        component_id,
        variant=variant,
        framework=framework,
        styling=styling,
        props=props,
        code=code,
        status=status,
    )
    if component is None:
        return {"error": "not_found", "id": component_id}
    return {"updated": True, "component": component}


async def delete_component(store: FrontendStore, component_id: int) -> dict[str, Any]:
    deleted = await store.delete_component(component_id)
    return {"deleted": deleted > 0, "id": component_id, "deleted_count": deleted}
