"""Tools de Storybook Story — CRUD que persiste a story fornecida pelo agente.

O agente gera o código-fonte da story (CSF 3.0) e a lista de estados; estas tools
persistem no banco do tenant e devolvem o registro com `id`. Thin wrappers sobre o
`FrontendStore`."""

from __future__ import annotations

from typing import Any

from ..db.store import FrontendStore


async def save_story(
    store: FrontendStore,
    component: str,
    title: str | None = None,
    framework: str | None = None,
    stories: Any = None,
    code: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    story = await store.save_story(
        component=component,
        title=title,
        framework=framework,
        stories=stories,
        code=code,
        status=status,
    )
    return {"saved": True, "story": story}


async def list_stories(
    store: FrontendStore, component: str | None = None, status: str | None = None
) -> dict[str, Any]:
    stories = await store.list_stories(component=component, status=status)
    return {
        "total": len(stories),
        "filters": {"component": component, "status": status},
        "stories": stories,
    }


async def get_story(store: FrontendStore, story_id: int) -> dict[str, Any]:
    story = await store.get_story(story_id)
    if story is None:
        return {"error": "not_found", "id": story_id}
    return story


async def update_story(
    store: FrontendStore,
    story_id: int,
    title: str | None = None,
    framework: str | None = None,
    stories: Any = None,
    code: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    story = await store.update_story(
        story_id,
        title=title,
        framework=framework,
        stories=stories,
        code=code,
        status=status,
    )
    if story is None:
        return {"error": "not_found", "id": story_id}
    return {"updated": True, "story": story}


async def delete_story(store: FrontendStore, story_id: int) -> dict[str, Any]:
    deleted = await store.delete_story(story_id)
    return {"deleted": deleted > 0, "id": story_id, "deleted_count": deleted}
