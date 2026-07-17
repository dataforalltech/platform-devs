"""Tools de User Story — CRUD que persiste a história fornecida pelo agente chamador.

O agente gera a história (papel/objetivo/benefício/critérios de aceite); estas tools
persistem no banco do tenant e devolvem o registro com `id`. Thin wrappers sobre o
`ProductOwnerStore` (validação leve + envelope de resposta)."""

from __future__ import annotations

from typing import Any

from ..db.store import ProductOwnerStore


async def save_user_story(
    store: ProductOwnerStore,
    feature: str,
    role: str,
    goal: str | None = None,
    benefit: str | None = None,
    story: str | None = None,
    acceptance_criteria: Any = None,
    priority: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    saved = await store.save_user_story(
        feature=feature,
        role=role,
        goal=goal,
        benefit=benefit,
        story=story,
        acceptance_criteria=acceptance_criteria,
        priority=priority,
        status=status,
    )
    return {"saved": True, "user_story": saved}


async def list_user_stories(
    store: ProductOwnerStore,
    feature: str | None = None,
    role: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    stories = await store.list_user_stories(feature=feature, role=role, status=status)
    return {
        "total": len(stories),
        "filters": {"feature": feature, "role": role, "status": status},
        "user_stories": stories,
    }


async def get_user_story(store: ProductOwnerStore, story_id: int) -> dict[str, Any]:
    story = await store.get_user_story(story_id)
    if story is None:
        return {"error": "not_found", "id": story_id}
    return story


async def update_user_story(
    store: ProductOwnerStore,
    story_id: int,
    role: str | None = None,
    goal: str | None = None,
    benefit: str | None = None,
    story: str | None = None,
    acceptance_criteria: Any = None,
    priority: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    updated = await store.update_user_story(
        story_id,
        role=role,
        goal=goal,
        benefit=benefit,
        story=story,
        acceptance_criteria=acceptance_criteria,
        priority=priority,
        status=status,
    )
    if updated is None:
        return {"error": "not_found", "id": story_id}
    return {"updated": True, "user_story": updated}


async def delete_user_story(store: ProductOwnerStore, story_id: int) -> dict[str, Any]:
    deleted = await store.delete_user_story(story_id)
    return {"deleted": deleted > 0, "id": story_id, "deleted_count": deleted}
