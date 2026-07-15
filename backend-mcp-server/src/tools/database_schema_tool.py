"""Tools de Database Schema — CRUD que persiste o schema fornecido pelo agente.

O agente gera o schema (atributos/relacionamentos/índices/constraints); estas tools
persistem no banco do tenant e devolvem o registro com `id`. Histórico por entidade
(chave surrogate `id`). Thin wrappers sobre o `BackendStore`."""

from __future__ import annotations

from typing import Any

from ..db.store import BackendStore


async def save_database_schema(
    store: BackendStore,
    entity: str,
    database_name: str,
    attributes: Any = None,
    relationships: Any = None,
    indexes: Any = None,
    constraints: Any = None,
    status: str | None = None,
) -> dict[str, Any]:
    schema = await store.save_database_schema(
        entity=entity,
        database_name=database_name,
        attributes=attributes,
        relationships=relationships,
        indexes=indexes,
        constraints=constraints,
        status=status,
    )
    return {"saved": True, "database_schema": schema}


async def list_database_schemas(
    store: BackendStore,
    entity: str | None = None,
    database_name: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    schemas = await store.list_database_schemas(entity=entity, database_name=database_name, status=status)
    return {
        "total": len(schemas),
        "filters": {"entity": entity, "database_name": database_name, "status": status},
        "database_schemas": schemas,
    }


async def get_database_schema(store: BackendStore, schema_id: int) -> dict[str, Any]:
    schema = await store.get_database_schema(schema_id)
    if schema is None:
        return {"error": "not_found", "id": schema_id}
    return schema


async def update_database_schema(
    store: BackendStore,
    schema_id: int,
    database_name: str | None = None,
    attributes: Any = None,
    relationships: Any = None,
    indexes: Any = None,
    constraints: Any = None,
    status: str | None = None,
) -> dict[str, Any]:
    schema = await store.update_database_schema(
        schema_id,
        database_name=database_name,
        attributes=attributes,
        relationships=relationships,
        indexes=indexes,
        constraints=constraints,
        status=status,
    )
    if schema is None:
        return {"error": "not_found", "id": schema_id}
    return {"updated": True, "database_schema": schema}


async def delete_database_schema(store: BackendStore, schema_id: int) -> dict[str, Any]:
    deleted = await store.delete_database_schema(schema_id)
    return {"deleted": deleted > 0, "id": schema_id, "deleted_count": deleted}
