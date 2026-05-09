"""Ferramentas de gerenciamento de planos de teste."""

from __future__ import annotations

from typing import Any

from ..db.store import TestStore

_VALID_STATUSES = {"active", "completed", "archived"}


def create_test_plan(
    store: TestStore,
    *,
    title: str,
    scope: str,
    feature: str | None = None,
) -> dict[str, Any]:
    """Cria um plano de testes para uma feature ou endpoint."""
    if not title or not scope:
        return {"error": "ValidationError", "details": "title e scope são obrigatórios"}
    return store.create_plan(title=title, scope=scope, feature=feature)


def get_test_plan(
    store: TestStore,
    *,
    plan_id: str,
    include_scenarios: bool = False,
) -> dict[str, Any]:
    """Retorna plano completo com cobertura, resultados e findings."""
    if not plan_id:
        return {"error": "ValidationError", "details": "plan_id é obrigatório"}
    plan = store.get_plan(plan_id)
    if not plan:
        return {"error": "not_found", "details": f"Plano '{plan_id}' não encontrado"}
    if include_scenarios:
        plan["scenarios"] = store.get_scenarios(plan_id)
    return plan


def list_test_plans(
    store: TestStore,
    *,
    status: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Lista planos de teste, opcionalmente filtrados por status."""
    if status and status not in _VALID_STATUSES:
        return {"error": "ValidationError", "details": f"status deve ser um de: {sorted(_VALID_STATUSES)}"}
    plans = store.list_plans(status=status, limit=min(limit, 100))
    return {"count": len(plans), "plans": plans}
