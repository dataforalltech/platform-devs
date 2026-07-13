"""Tools de Test Plan — CRUD que persiste o plano fornecido pelo agente chamador.

O agente gera o conteúdo (objetivos/níveis/ambientes/cronograma); estas tools
persistem no banco do tenant e devolvem o registro com `id`. Thin wrappers sobre o
`QAEngineerStore` (validação leve + envelope de resposta)."""

from __future__ import annotations

from typing import Any

from ..db.store import QAEngineerStore


async def save_test_plan(
    store: QAEngineerStore,
    feature: str,
    content: Any,
    scope: str = "full",
    team: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    plan = await store.save_test_plan(feature=feature, content=content, scope=scope, team=team, status=status)
    return {"saved": True, "test_plan": plan}


async def list_test_plans(
    store: QAEngineerStore, feature: str | None = None, status: str | None = None
) -> dict[str, Any]:
    plans = await store.list_test_plans(feature=feature, status=status)
    return {"total": len(plans), "filters": {"feature": feature, "status": status}, "test_plans": plans}


async def get_test_plan(store: QAEngineerStore, plan_id: int) -> dict[str, Any]:
    plan = await store.get_test_plan(plan_id)
    if plan is None:
        return {"error": "not_found", "id": plan_id}
    return plan


async def update_test_plan(
    store: QAEngineerStore,
    plan_id: int,
    scope: str | None = None,
    team: str | None = None,
    content: Any = None,
    status: str | None = None,
) -> dict[str, Any]:
    plan = await store.update_test_plan(plan_id, scope=scope, team=team, content=content, status=status)
    if plan is None:
        return {"error": "not_found", "id": plan_id}
    return {"updated": True, "test_plan": plan}


async def delete_test_plan(store: QAEngineerStore, plan_id: int) -> dict[str, Any]:
    deleted = await store.delete_test_plan(plan_id)
    return {"deleted": deleted > 0, "id": plan_id, "deleted_count": deleted}
