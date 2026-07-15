"""Tools de Backlog Item — CRUD que persiste o item priorizado fornecido pelo agente.

O antigo `calculate_rice_score` (cálculo puro RICE = Reach×Impact×Confidence / Effort)
foi **dobrado** aqui: `save_backlog_item` chama o calculador determinístico para
preencher `score` quando o agente não o fornece (e os campos RICE estão presentes), e
persiste o resultado. O calculador segue exposto como função pura
(`calculate_rice_score`) para reuso/teste. A ordenação da `list` é por `score` (desc),
então o backlog persistido já sai priorizado."""

from __future__ import annotations

from typing import Any

from ..db.store import ProductOwnerStore


def _normalize_confidence(confidence: float) -> float:
    """Normaliza confiança: aceita 0–1 (fração) ou 1–100 (percentual) → 0–1."""
    return confidence / 100.0 if confidence > 1 else confidence


def calculate_rice_score(
    reach: float,
    impact: float,
    confidence: float,
    effort: float,
    feature: str | None = None,
) -> dict[str, Any]:
    """Cálculo puro: (Reach × Impact × Confidence) / Effort. Determinístico.

    `confidence` aceita fração 0–1 (ex.: 0.8) ou percentual 1–100 (ex.: 80),
    normalizado para 0–1. Retorna `{"error": ...}` em input inválido (effort<=0, etc.).
    """
    errors: list[str] = []
    if reach < 0:
        errors.append("reach must be >= 0")
    if impact <= 0:
        errors.append("impact must be > 0")
    if confidence <= 0:
        errors.append("confidence must be > 0")
    if effort <= 0:
        errors.append("effort must be > 0 (division by zero)")

    confidence_fraction = _normalize_confidence(confidence)
    if confidence_fraction > 1:
        errors.append("confidence out of range (expected 0-1 fraction or 1-100 percent)")

    if errors:
        return {"error": "invalid_input", "details": errors, "feature": feature}

    score = (reach * impact * confidence_fraction) / effort
    return {
        "feature": feature,
        "score": round(score, 2),
        "formula": "(reach * impact * confidence) / effort",
        "breakdown": {
            "reach": reach,
            "impact": impact,
            "confidence": round(confidence_fraction, 4),
            "confidence_percent": round(confidence_fraction * 100, 2),
            "effort": effort,
            "numerator": round(reach * impact * confidence_fraction, 4),
        },
    }


def _maybe_rice_score(
    reach: float | None, impact: float | None, confidence: float | None, effort: float | None
) -> float | None:
    """Calcula o RICE score se todos os campos vierem e forem válidos; senão None."""
    if None in (reach, impact, confidence, effort):
        return None
    result = calculate_rice_score(float(reach), float(impact), float(confidence), float(effort))  # type: ignore[arg-type]
    computed = result.get("score")
    return float(computed) if isinstance(computed, (int, float)) else None


async def save_backlog_item(
    store: ProductOwnerStore,
    name: str,
    framework: str = "RICE",
    reach: float | None = None,
    impact: float | None = None,
    confidence: float | None = None,
    effort: float | None = None,
    score: float | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """Persiste um item de backlog. Se `score` não vier e os campos RICE estiverem
    presentes (framework RICE), calcula-o determinísticamente e persiste."""
    final_score = score
    if final_score is None and (framework or "RICE").upper() == "RICE":
        final_score = _maybe_rice_score(reach, impact, confidence, effort)
    item = await store.save_backlog_item(
        name=name,
        framework=framework,
        reach=reach,
        impact=impact,
        confidence=confidence,
        effort=effort,
        score=final_score,
        status=status,
    )
    return {"saved": True, "backlog_item": item}


async def list_backlog_items(
    store: ProductOwnerStore, framework: str | None = None, status: str | None = None
) -> dict[str, Any]:
    items = await store.list_backlog_items(framework=framework, status=status)
    return {
        "total": len(items),
        "filters": {"framework": framework, "status": status},
        "backlog_items": items,
    }


async def get_backlog_item(store: ProductOwnerStore, item_id: int) -> dict[str, Any]:
    item = await store.get_backlog_item(item_id)
    if item is None:
        return {"error": "not_found", "id": item_id}
    return item


async def update_backlog_item(
    store: ProductOwnerStore,
    item_id: int,
    framework: str | None = None,
    reach: float | None = None,
    impact: float | None = None,
    confidence: float | None = None,
    effort: float | None = None,
    score: float | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    item = await store.update_backlog_item(
        item_id,
        framework=framework,
        reach=reach,
        impact=impact,
        confidence=confidence,
        effort=effort,
        score=score,
        status=status,
    )
    if item is None:
        return {"error": "not_found", "id": item_id}
    return {"updated": True, "backlog_item": item}


async def delete_backlog_item(store: ProductOwnerStore, item_id: int) -> dict[str, Any]:
    deleted = await store.delete_backlog_item(item_id)
    return {"deleted": deleted > 0, "id": item_id, "deleted_count": deleted}
