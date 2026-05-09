"""Ferramentas de validação, findings e double-check de planos de teste."""

from __future__ import annotations

from typing import Any

from ..db.store import TestStore

_VALID_SEVERITIES = {"critical", "high", "medium", "low"}
_VALID_FINDING_STATUSES = {"open", "resolved", "accepted"}


def add_finding(
    store: TestStore,
    *,
    plan_id: str,
    severity: str,
    title: str,
    description: str,
    evidence: str | None = None,
) -> dict[str, Any]:
    """Registra um bug, problema ou risco encontrado durante os testes."""
    if not plan_id or not title or not description:
        return {"error": "ValidationError", "details": "plan_id, title e description são obrigatórios"}
    if severity not in _VALID_SEVERITIES:
        return {
            "error": "ValidationError",
            "details": f"severity deve ser um de: {sorted(_VALID_SEVERITIES)}",
        }
    if not store.get_plan(plan_id):
        return {"error": "not_found", "details": f"Plano '{plan_id}' não encontrado"}

    result = store.add_finding(
        plan_id=plan_id,
        severity=severity,
        title=title,
        description=description,
        evidence=evidence,
    )
    if severity == "critical":
        result["warning"] = "Finding CRITICAL registrado — o plano NAO pode ser aprovado enquanto houver findings criticos em aberto."
    return result


def double_check(
    store: TestStore,
    *,
    plan_id: str,
) -> dict[str, Any]:
    """Executa double-check completo do plano: cenários não executados, falhas abertas e findings críticos."""
    if not plan_id:
        return {"error": "ValidationError", "details": "plan_id é obrigatório"}
    if not store.get_plan(plan_id):
        return {"error": "not_found", "details": f"Plano '{plan_id}' não encontrado"}

    result = store.double_check(plan_id)
    summary = result.get("summary", {})

    if summary.get("ready_to_ship"):
        result["verdict"] = "APROVADO — todos os cenários executados, sem falhas abertas e sem findings criticos."
    else:
        blockers = []
        if summary.get("not_executed_count", 0) > 0:
            blockers.append(f"{summary['not_executed_count']} cenario(s) nao executado(s)")
        if summary.get("failed_count", 0) > 0:
            blockers.append(f"{summary['failed_count']} cenario(s) com falha")
        if summary.get("critical_findings", 0) > 0:
            blockers.append(f"{summary['critical_findings']} finding(s) critico(s) em aberto")
        result["verdict"] = "BLOQUEADO — " + "; ".join(blockers)

    return result


def get_validation_status(
    store: TestStore,
    *,
    plan_id: str,
) -> dict[str, Any]:
    """Retorna status completo de validação: cobertura, pass rate, findings por severidade e grade."""
    if not plan_id:
        return {"error": "ValidationError", "details": "plan_id é obrigatório"}
    if not store.get_plan(plan_id):
        return {"error": "not_found", "details": f"Plano '{plan_id}' não encontrado"}

    result = store.get_validation_status(plan_id)

    # Adicionar interpretação do grade
    grade = result.get("grade", "?")
    grade_desc = {
        "A": "Excelente — cobertura alta, alta taxa de aprovação, sem findings graves",
        "B": "Bom — pequenas lacunas de cobertura ou findings de baixa severidade",
        "C": "Regular — cobertura ou taxa de aprovação abaixo do ideal",
        "D": "Insuficiente — cobertura baixa ou muitos findings de alta severidade",
        "F": "Reprovado — findings criticos em aberto ou cobertura/aprovacao muito baixa",
    }
    result["grade_description"] = grade_desc.get(grade, "Desconhecido")

    if not result.get("ready_to_ship"):
        result["ship_blockers"] = []
        if result.get("coverage_pct", 0) < 80:
            result["ship_blockers"].append(f"Cobertura {result['coverage_pct']}% < 80% minimo")
        if result.get("pass_rate", 0) < 90:
            result["ship_blockers"].append(f"Pass rate {result['pass_rate']}% < 90% minimo")
        if result.get("findings_by_severity", {}).get("critical"):
            n = result["findings_by_severity"]["critical"]
            result["ship_blockers"].append(f"{n} finding(s) critico(s) em aberto")

    return result
