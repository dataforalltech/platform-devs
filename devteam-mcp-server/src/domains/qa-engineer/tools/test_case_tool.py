"""Tools de Test Case — CRUD que persiste os casos fornecidos pelo agente chamador.

O agente gera os passos/pré-condições/dados; estas tools persistem no banco do tenant
e devolvem o registro com `id`. Thin wrappers sobre o `QAEngineerStore`."""

from __future__ import annotations

from typing import Any

from ..db.store import QAEngineerStore


async def save_test_case(
    store: QAEngineerStore,
    feature: str,
    title: str,
    steps: Any,
    test_type: str = "functional",
    priority: str = "medium",
    preconditions: Any = None,
    expected_result: str | None = None,
    test_data: Any = None,
    status: str | None = None,
) -> dict[str, Any]:
    case = await store.save_test_case(
        feature=feature,
        title=title,
        steps=steps,
        test_type=test_type,
        priority=priority,
        preconditions=preconditions,
        expected_result=expected_result,
        test_data=test_data,
        status=status,
    )
    return {"saved": True, "test_case": case}


async def list_test_cases(
    store: QAEngineerStore,
    feature: str | None = None,
    test_type: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    cases = await store.list_test_cases(feature=feature, test_type=test_type, status=status)
    return {
        "total": len(cases),
        "filters": {"feature": feature, "test_type": test_type, "status": status},
        "test_cases": cases,
    }


async def get_test_case(store: QAEngineerStore, case_id: int) -> dict[str, Any]:
    case = await store.get_test_case(case_id)
    if case is None:
        return {"error": "not_found", "id": case_id}
    return case


async def update_test_case(
    store: QAEngineerStore,
    case_id: int,
    title: str | None = None,
    test_type: str | None = None,
    priority: str | None = None,
    preconditions: Any = None,
    steps: Any = None,
    expected_result: str | None = None,
    test_data: Any = None,
    status: str | None = None,
) -> dict[str, Any]:
    case = await store.update_test_case(
        case_id,
        title=title,
        test_type=test_type,
        priority=priority,
        preconditions=preconditions,
        steps=steps,
        expected_result=expected_result,
        test_data=test_data,
        status=status,
    )
    if case is None:
        return {"error": "not_found", "id": case_id}
    return {"updated": True, "test_case": case}


async def delete_test_case(store: QAEngineerStore, case_id: int) -> dict[str, Any]:
    deleted = await store.delete_test_case(case_id)
    return {"deleted": deleted > 0, "id": case_id, "deleted_count": deleted}
