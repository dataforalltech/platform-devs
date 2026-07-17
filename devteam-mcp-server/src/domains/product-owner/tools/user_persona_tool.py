"""Tools de User Persona — CRUD que persiste a persona fornecida pelo agente chamador.

O agente gera a persona (demografia/objetivos/dores/comportamentos); estas tools
persistem no banco do tenant e devolvem o registro com `id`. Thin wrappers sobre o
`ProductOwnerStore`."""

from __future__ import annotations

from typing import Any

from ..db.store import ProductOwnerStore


async def save_user_persona(
    store: ProductOwnerStore,
    name: str,
    segment: str | None = None,
    demographics: Any = None,
    goals: Any = None,
    pains: Any = None,
    behaviors: Any = None,
) -> dict[str, Any]:
    persona = await store.save_user_persona(
        name=name,
        segment=segment,
        demographics=demographics,
        goals=goals,
        pains=pains,
        behaviors=behaviors,
    )
    return {"saved": True, "user_persona": persona}


async def list_user_personas(
    store: ProductOwnerStore, segment: str | None = None, name: str | None = None
) -> dict[str, Any]:
    personas = await store.list_user_personas(segment=segment, name=name)
    return {
        "total": len(personas),
        "filters": {"segment": segment, "name": name},
        "user_personas": personas,
    }


async def get_user_persona(store: ProductOwnerStore, persona_id: int) -> dict[str, Any]:
    persona = await store.get_user_persona(persona_id)
    if persona is None:
        return {"error": "not_found", "id": persona_id}
    return persona


async def update_user_persona(
    store: ProductOwnerStore,
    persona_id: int,
    segment: str | None = None,
    demographics: Any = None,
    goals: Any = None,
    pains: Any = None,
    behaviors: Any = None,
) -> dict[str, Any]:
    persona = await store.update_user_persona(
        persona_id,
        segment=segment,
        demographics=demographics,
        goals=goals,
        pains=pains,
        behaviors=behaviors,
    )
    if persona is None:
        return {"error": "not_found", "id": persona_id}
    return {"updated": True, "user_persona": persona}


async def delete_user_persona(store: ProductOwnerStore, persona_id: int) -> dict[str, Any]:
    deleted = await store.delete_user_persona(persona_id)
    return {"deleted": deleted > 0, "id": persona_id, "deleted_count": deleted}
