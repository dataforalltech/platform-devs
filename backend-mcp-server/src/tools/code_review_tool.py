"""Tools de Code Review — CRUD que persiste a revisão fornecida pelo agente.

A antiga `review_backend_code` (que devolvia template fixo) vira persistência: o
agente produz os achados/scores e `save_code_review` os persiste como histórico
append-only por alvo. Thin wrappers sobre o `BackendStore`."""

from __future__ import annotations

from typing import Any

from ..db.store import BackendStore


async def save_code_review(
    store: BackendStore,
    target: str,
    language: str,
    focus: Any = None,
    findings: Any = None,
    security_score: float | None = None,
    performance_score: float | None = None,
    summary: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    review = await store.save_code_review(
        target=target,
        language=language,
        focus=focus,
        findings=findings,
        security_score=security_score,
        performance_score=performance_score,
        summary=summary,
        status=status,
    )
    return {"saved": True, "code_review": review}


async def list_code_reviews(
    store: BackendStore,
    target: str | None = None,
    language: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    reviews = await store.list_code_reviews(target=target, language=language, status=status)
    return {
        "total": len(reviews),
        "filters": {"target": target, "language": language, "status": status},
        "code_reviews": reviews,
    }


async def get_code_review(store: BackendStore, review_id: int) -> dict[str, Any]:
    review = await store.get_code_review(review_id)
    if review is None:
        return {"error": "not_found", "id": review_id}
    return review


async def delete_code_review(store: BackendStore, review_id: int) -> dict[str, Any]:
    deleted = await store.delete_code_review(review_id)
    return {"deleted": deleted > 0, "id": review_id, "deleted_count": deleted}
