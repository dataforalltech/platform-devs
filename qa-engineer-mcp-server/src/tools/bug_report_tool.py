"""Tools de Bug Report — CRUD que persiste o bug fornecido pelo agente chamador.

O antigo `classify_bug_severity` (cálculo puro impacto×frequência → severidade P1–P4
+ score) foi **dobrado** aqui: `save_bug_report` chama o classificador determinístico
para preencher `severity`/`score` quando o agente não os fornece, e persiste o
resultado. O classificador segue exposto como função pura (`classify_bug_severity`)
para reuso/teste."""

from __future__ import annotations

from typing import Any

from ..db.store import QAEngineerStore

_IMPACT_MAP = {"critical": 4, "high": 3, "medium": 2, "low": 1}
_FREQ_MAP = {"always": 4, "often": 3, "sometimes": 2, "rarely": 1}
_SLA = {"P1": "4h", "P2": "24h", "P3": "72h", "P4": "backlog"}
_RECOMMENDED_ACTION = {
    "P1": "Hotfix imediato, bloquear deploy",
    "P2": "Corrigir na próxima sprint",
    "P3": "Planejar correção",
    "P4": "Registrar no backlog",
}
VALID_SEVERITIES = frozenset(_SLA)


def classify_bug_severity(impact: str, frequency: str) -> tuple[str, float]:
    """Cálculo puro: (impact×frequency) → (severidade P1–P4, score). Determinístico."""
    score = _IMPACT_MAP.get(impact, 2) * _FREQ_MAP.get(frequency, 2)
    severity = "P1" if score >= 9 else "P2" if score >= 6 else "P3" if score >= 3 else "P4"
    return severity, float(score)


async def save_bug_report(
    store: QAEngineerStore,
    title: str,
    impact: str = "medium",
    frequency: str = "sometimes",
    severity: str | None = None,
    score: float | None = None,
    steps: Any = None,
    description: str | None = None,
    status: str = "open",
) -> dict[str, Any]:
    """Persiste um bug. Se severity/score não vierem, calcula-os de impact×frequency."""
    computed_severity, computed_score = classify_bug_severity(impact, frequency)
    final_severity = severity or computed_severity
    if final_severity not in VALID_SEVERITIES:
        return {"error": "invalid_severity", "severity": final_severity, "valid": sorted(VALID_SEVERITIES)}
    final_score = computed_score if score is None else score
    bug = await store.save_bug_report(
        title=title,
        severity=final_severity,
        impact=impact,
        frequency=frequency,
        score=final_score,
        steps=steps,
        description=description,
        status=status,
    )
    return {
        "saved": True,
        "bug_report": bug,
        "sla": _SLA[final_severity],
        "recommended_action": _RECOMMENDED_ACTION[final_severity],
    }


async def list_bug_reports(
    store: QAEngineerStore, severity: str | None = None, status: str | None = None
) -> dict[str, Any]:
    bugs = await store.list_bug_reports(severity=severity, status=status)
    return {"total": len(bugs), "filters": {"severity": severity, "status": status}, "bug_reports": bugs}


async def get_bug_report(store: QAEngineerStore, bug_id: int) -> dict[str, Any]:
    bug = await store.get_bug_report(bug_id)
    if bug is None:
        return {"error": "not_found", "id": bug_id}
    return bug


async def update_bug_status(store: QAEngineerStore, bug_id: int, status: str) -> dict[str, Any]:
    bug = await store.update_bug_status(bug_id, status)
    if bug is None:
        return {"error": "not_found", "id": bug_id}
    return {"updated": True, "bug_report": bug}


async def delete_bug_report(store: QAEngineerStore, bug_id: int) -> dict[str, Any]:
    deleted = await store.delete_bug_report(bug_id)
    return {"deleted": deleted > 0, "id": bug_id, "deleted_count": deleted}
