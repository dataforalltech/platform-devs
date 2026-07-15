"""Tools de CVSS Assessment — CRUD que persiste a avaliação fornecida pelo agente.

O cálculo determinístico CVSS v3.1 (base score/severidade/subscores a partir do vetor)
foi **dobrado** aqui: `save_cvss_assessment` chama o calculador puro para preencher
`base_score`/`severity`/`metrics` quando o agente não os fornece, e persiste o
resultado. O calculador segue exposto como função pura (`calculate_cvss`) para
reuso/teste. Thin wrappers sobre o `SecurityStore`."""

from __future__ import annotations

import math
from typing import Any

from ..db.store import SecurityStore

# Pesos oficiais do CVSS v3.1 (base metrics).
_CVSS_WEIGHTS: dict[str, dict[str, float]] = {
    "AV": {"N": 0.85, "A": 0.62, "L": 0.55, "P": 0.20},
    "AC": {"L": 0.77, "H": 0.44},
    "UI": {"N": 0.85, "R": 0.62},
    "C": {"H": 0.56, "L": 0.22, "N": 0.0},
    "I": {"H": 0.56, "L": 0.22, "N": 0.0},
    "A": {"H": 0.56, "L": 0.22, "N": 0.0},
}
_PR_WEIGHTS: dict[str, dict[str, float]] = {
    "U": {"N": 0.85, "L": 0.62, "H": 0.27},
    "C": {"N": 0.85, "L": 0.68, "H": 0.50},
}
_REQUIRED_METRICS = ("AV", "AC", "PR", "UI", "S", "C", "I", "A")


def _cvss_roundup(value: float) -> float:
    int_input = round(value * 100000)
    if int_input % 10000 == 0:
        return int_input / 100000.0
    return (math.floor(int_input / 10000) + 1) / 10.0


def _severity_rating(score: float) -> str:
    if score == 0:
        return "None"
    if score < 4.0:
        return "Low"
    if score < 7.0:
        return "Medium"
    if score < 9.0:
        return "High"
    return "Critical"


def calculate_cvss(vector: str) -> dict[str, Any]:
    """Cálculo puro CVSS v3.1 base score a partir de um vetor. Determinístico.

    Ex: CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H
    Retorna {"error": ...} em vetor incompleto/inválido (não persiste)."""
    metrics: dict[str, str] = {}
    for part in vector.strip().split("/"):
        if ":" in part and not part.upper().startswith("CVSS"):
            k, v = part.split(":", 1)
            metrics[k.upper()] = v.upper()

    missing = [m for m in _REQUIRED_METRICS if m not in metrics]
    if missing:
        return {
            "error": "vetor_incompleto",
            "missing_metrics": missing,
            "expected_format": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",
        }

    try:
        scope = metrics["S"]  # U (Unchanged) ou C (Changed)
        iss = 1 - (
            (1 - _CVSS_WEIGHTS["C"][metrics["C"]])
            * (1 - _CVSS_WEIGHTS["I"][metrics["I"]])
            * (1 - _CVSS_WEIGHTS["A"][metrics["A"]])
        )
        if scope == "U":
            impact = 6.42 * iss
        else:
            impact = 7.52 * (iss - 0.029) - 3.25 * (iss - 0.02) ** 15

        exploitability = (
            8.22
            * _CVSS_WEIGHTS["AV"][metrics["AV"]]
            * _CVSS_WEIGHTS["AC"][metrics["AC"]]
            * _PR_WEIGHTS[scope][metrics["PR"]]
            * _CVSS_WEIGHTS["UI"][metrics["UI"]]
        )

        if impact <= 0:
            base = 0.0
        elif scope == "U":
            base = _cvss_roundup(min(impact + exploitability, 10))
        else:
            base = _cvss_roundup(min(1.08 * (impact + exploitability), 10))
    except (KeyError, ValueError) as exc:
        return {"error": "valor_de_metrica_invalido", "detail": str(exc)}

    return {
        "vector": vector.strip(),
        "base_score": base,
        "severity": _severity_rating(base),
        "impact_subscore": round(impact, 1),
        "exploitability_subscore": round(exploitability, 1),
        "metrics": metrics,
    }


async def save_cvss_assessment(
    store: SecurityStore,
    vector: str,
    label: str | None = None,
    base_score: float | None = None,
    severity: str | None = None,
    metrics: Any = None,
    status: str | None = None,
) -> dict[str, Any]:
    """Persiste uma avaliação CVSS. Se base_score/severity/metrics não vierem, calcula-os
    deterministicamente do vetor (CVSS v3.1). Vetor inválido → erro sem persistir."""
    computed = calculate_cvss(vector)
    if "error" in computed:
        return computed
    final_score = computed["base_score"] if base_score is None else base_score
    final_severity = severity or computed["severity"]
    final_metrics = metrics if metrics is not None else computed["metrics"]
    assessment = await store.save_cvss_assessment(
        vector=vector.strip(),
        label=label,
        base_score=final_score,
        severity=final_severity,
        metrics=final_metrics,
        status=status,
    )
    return {
        "saved": True,
        "cvss_assessment": assessment,
        "impact_subscore": computed["impact_subscore"],
        "exploitability_subscore": computed["exploitability_subscore"],
    }


async def list_cvss_assessments(
    store: SecurityStore, severity: str | None = None, label: str | None = None
) -> dict[str, Any]:
    items = await store.list_cvss_assessments(severity=severity, label=label)
    return {
        "total": len(items),
        "filters": {"severity": severity, "label": label},
        "cvss_assessments": items,
    }


async def get_cvss_assessment(store: SecurityStore, assessment_id: int) -> dict[str, Any]:
    item = await store.get_cvss_assessment(assessment_id)
    if item is None:
        return {"error": "not_found", "id": assessment_id}
    return item


async def delete_cvss_assessment(store: SecurityStore, assessment_id: int) -> dict[str, Any]:
    deleted = await store.delete_cvss_assessment(assessment_id)
    return {"deleted": deleted > 0, "id": assessment_id, "deleted_count": deleted}
