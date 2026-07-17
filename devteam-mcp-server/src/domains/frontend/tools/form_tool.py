"""Tools de Formulário — CRUD que persiste o formulário fornecido pelo agente.

O agente gera o código-fonte (React Hook Form + Zod/Yup) e o esquema de campos;
estas tools persistem no banco do tenant e devolvem o registro com `id`. Thin
wrappers sobre o `FrontendStore`."""

from __future__ import annotations

from typing import Any

from ..db.store import FrontendStore


async def save_form(
    store: FrontendStore,
    name: str,
    library: str | None = None,
    validation: str | None = None,
    fields: Any = None,
    code: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    form = await store.save_form(
        name=name,
        library=library,
        validation=validation,
        fields=fields,
        code=code,
        status=status,
    )
    return {"saved": True, "form": form}


async def list_forms(
    store: FrontendStore, name: str | None = None, status: str | None = None
) -> dict[str, Any]:
    forms = await store.list_forms(name=name, status=status)
    return {"total": len(forms), "filters": {"name": name, "status": status}, "forms": forms}


async def get_form(store: FrontendStore, form_id: int) -> dict[str, Any]:
    form = await store.get_form(form_id)
    if form is None:
        return {"error": "not_found", "id": form_id}
    return form


async def update_form(
    store: FrontendStore,
    form_id: int,
    library: str | None = None,
    validation: str | None = None,
    fields: Any = None,
    code: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    form = await store.update_form(
        form_id,
        library=library,
        validation=validation,
        fields=fields,
        code=code,
        status=status,
    )
    if form is None:
        return {"error": "not_found", "id": form_id}
    return {"updated": True, "form": form}


async def delete_form(store: FrontendStore, form_id: int) -> dict[str, Any]:
    deleted = await store.delete_form(form_id)
    return {"deleted": deleted > 0, "id": form_id, "deleted_count": deleted}
