"""Store do test-mcp — 100% sobre o ORM canônico (`platform_database.orm`).

Reescrito do psycopg2 cru para o **Repository** de alto nível + Query IR, ligado ao
pool **do tenant** (resolvido credencial-zero via `for_tenant`/`get_pool_for_tenant`,
ORM-H-12). Roda dual-db: o mesmo código serve MySQL (banco-por-tenant) e PostgreSQL
(schema-por-tenant) — o dialeto do pool decide o SQL.

Sem SQL manual: cada read/write cai no Repository (`find`/`insert`/`update_where`/
`upsert`/`count`). As leituras que "não encaixam" no CRUD trivial resolvem
canonicamente com **agregação em Python** sobre `find().rows()` (dado pequeno; evita
GROUP BY / LEFT JOIN LATERAL e mantém orm-lint --strict limpo):
  * o "último status por cenário" (antes um LEFT JOIN LATERAL) vira ordenação em
    Python por ``executed_at``;
  * as contagens por status (get_plan/get_validation_status/double_check) viram
    ``set``/``sum`` sobre as linhas;
  * o resultado de item de checklist por (run_id, item_id) usa
    ``upsert(conflict_columns=["run_id", "item_id"])``.

Convenções: `PLATFORM_CONVENTIONS` (soft-delete `excluded=0`, auditoria
`id_user_*`/`timestamp_refresh`). Como `id_user_created` é NOT NULL sem default, todo
write carimba o usuário-sistema (`_SYSTEM_USER`).
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any

from platform_database.orm import Sort, SortDirection

from ..models import (
    BugReportRow,
    ChecklistItemRow,
    ChecklistResultRow,
    ChecklistRow,
    ChecklistRunRow,
    ScenarioRow,
    TestCaseRow,
    TestPlanRow,
)
from .schema import (
    BUG_REPORTS_TABLE,
    CHECKLIST_ITEMS_TABLE,
    CHECKLIST_RESULTS_TABLE,
    CHECKLIST_RUNS_TABLE,
    CHECKLISTS_TABLE,
    TEST_CASES_TABLE,
    TEST_PLANS_TABLE,
    TEST_SCENARIOS_TABLE,
)

# Usuário-sistema carimbado nas colunas de auditoria (id_user_created/id_user_modify).
_SYSTEM_USER = 0

# Ordem de severidade p/ ordenar findings abertos (menor = mais grave).
_SEVERITY_RANK = {"critical": 1, "high": 2, "medium": 3}

# Status que contam como "verificado" num item de checklist required.
_DONE_STATUSES = {"passed", "failed", "na"}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _new_id(prefix: str = "run") -> str:
    """Gera ID natural com prefixo (usado nas PKs naturais: run_)."""
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _to_int_id(plan_id: str | int) -> int:
    """Converte plan_id para int — o banco usa INTEGER como PK surrogate."""
    try:
        return int(plan_id)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"plan_id inválido: {plan_id!r} — deve ser numérico") from exc


def _jsonable(row: dict[str, Any]) -> dict[str, Any]:
    """Converte datetimes das colunas padrão (create_on/timestamp_refresh) em ISO str,
    para o `json.dumps` do envelope MCP não quebrar."""
    out: dict[str, Any] = {}
    for key, value in row.items():
        out[key] = value.isoformat() if isinstance(value, (datetime, date)) else value
    return out


def _shape_plan(row: dict[str, Any]) -> dict[str, Any]:
    """Forma canônica da linha de plano: datetimes -> ISO; ``plan_scope`` -> ``scope``."""
    shaped = _jsonable(row)
    shaped["scope"] = shaped.pop("plan_scope", None)
    return shaped


def _grade(coverage: float, pass_rate: float, findings: dict) -> str:
    """Calcula grade de qualidade (idêntico à versão legada)."""
    if findings.get("critical"):
        return "F"
    score = (coverage * 0.4) + (pass_rate * 0.6)
    high = findings.get("high", 0)
    score -= high * 5
    if score >= 90:
        return "A"
    if score >= 80:
        return "B"
    if score >= 70:
        return "C"
    if score >= 60:
        return "D"
    return "F"


class TestStore:
    """Store tenant-scoped: 8 repositórios ligados ao pool do tenant.

    Recebe uma ``TenantSession`` (de ``platform_database.orm.for_tenant``) e cria os
    repositórios canônicos por ela — ``require_tenant=True`` (fail-closed ORM-H-02),
    credencial-zero (a sessão nunca expõe senha/host).
    """

    # Helpers estáticos preservados para compatibilidade / testes de unidade.
    _to_int_id = staticmethod(_to_int_id)
    _grade = staticmethod(_grade)

    def __init__(self, session: Any) -> None:
        self._plans = session.repository(TestPlanRow, table_name=TEST_PLANS_TABLE)
        self._scenarios = session.repository(ScenarioRow, table_name=TEST_SCENARIOS_TABLE)
        self._cases = session.repository(TestCaseRow, table_name=TEST_CASES_TABLE)
        self._bugs = session.repository(BugReportRow, table_name=BUG_REPORTS_TABLE)
        self._checklists = session.repository(ChecklistRow, table_name=CHECKLISTS_TABLE)
        self._items = session.repository(ChecklistItemRow, table_name=CHECKLIST_ITEMS_TABLE)
        self._runs = session.repository(ChecklistRunRow, table_name=CHECKLIST_RUNS_TABLE)
        self._results = session.repository(ChecklistResultRow, table_name=CHECKLIST_RESULTS_TABLE)

    # -- helpers de leitura (dict cru) ---------------------------------------- #

    async def _plan_row(self, pid: int) -> dict[str, Any] | None:
        res = await self._plans.find(where={"id": pid}, limit=1)
        rows = res.rows()
        return rows[0] if rows else None

    async def _cases_for(self, pid: int) -> list[dict[str, Any]]:
        return (await self._cases.find(where={"plan_id": pid})).rows()

    async def _touch_plan(self, pid: int, now: str) -> None:
        await self._plans.update_where({"id": pid}, {"updated_at": now}, user_id=_SYSTEM_USER)

    # ─────────────────────────────────────────────────────────────────────── #
    # TEST PLANS
    # ─────────────────────────────────────────────────────────────────────── #

    async def create_plan(self, title: str, scope: str, feature: str | None = None) -> dict[str, Any]:
        """Cria novo plano de testes."""
        now = _now()
        res = await self._plans.insert(
            {
                "title": title,
                "plan_scope": scope,
                "feature": feature,
                "status": "active",
                "created_at": now,
                "updated_at": now,
            },
            user_id=_SYSTEM_USER,
        )
        return {
            "id": int(res.returned_id) if res.returned_id is not None else 0,
            "title": title,
            "scope": scope,
            "feature": feature,
            "status": "active",
            "created_at": now,
        }

    async def get_plan(self, plan_id: str | int) -> dict[str, Any] | None:
        """Retorna plano completo com estatísticas (contagens + cobertura)."""
        pid = _to_int_id(plan_id)
        row = await self._plan_row(pid)
        if row is None:
            return None

        scenarios_count = await self._scenarios.count(where={"plan_id": pid})
        results_count = await self._cases.count(where={"plan_id": pid})
        findings_count = await self._bugs.count(where={"plan_id": pid})

        cases = await self._cases_for(pid)
        pending = len({c["scenario_id"] for c in cases if c.get("status") == "pending"})
        passed = len({c["scenario_id"] for c in cases if c.get("status") == "passed"})
        failed = len({c["scenario_id"] for c in cases if c.get("status") == "failed"})

        plan = _shape_plan(row)
        plan["scenarios_count"] = scenarios_count
        plan["results_count"] = results_count
        plan["findings_count"] = findings_count
        plan["coverage"] = {"passed": passed, "failed": failed, "pending": pending}
        return plan

    async def list_plans(self, status: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        """Lista planos de testes com filtros opcionais (ordenado por updated_at DESC)."""
        res = await self._plans.find(
            where={"status": status} if status else None,
            order_by=[Sort(column="updated_at", direction=SortDirection.DESC)],
            limit=limit,
        )
        out: list[dict[str, Any]] = []
        for row in res.rows():
            plan = _shape_plan(row)
            plan["scenarios_count"] = await self._scenarios.count(where={"plan_id": row["id"]})
            out.append(plan)
        return out

    # ─────────────────────────────────────────────────────────────────────── #
    # SCENARIOS
    # ─────────────────────────────────────────────────────────────────────── #

    async def add_scenario(
        self,
        plan_id: str | int,
        name: str,
        category: str,
        steps: str,
        expected_result: str,
        priority: str = "medium",
        preconditions: str | None = None,
    ) -> dict[str, Any]:
        """Adiciona cenário ao plano."""
        pid = _to_int_id(plan_id)
        now = _now()
        res = await self._scenarios.insert(
            {
                "plan_id": pid,
                "name": name,
                "category": category,
                "priority": priority,
                "preconditions": preconditions,
                "steps": steps,
                "expected_result": expected_result,
                "created_at": now,
            },
            user_id=_SYSTEM_USER,
        )
        await self._touch_plan(pid, now)
        return {
            "scenario_id": int(res.returned_id) if res.returned_id is not None else 0,
            "plan_id": plan_id,
            "name": name,
            "category": category,
            "priority": priority,
        }

    async def record_result(
        self,
        plan_id: str | int,
        scenario_id: int,
        status: str,
        actual_result: str | None = None,
        notes: str | None = None,
        evidence: str | None = None,
    ) -> dict[str, Any]:
        """Registra resultado de execução de cenário (append-only)."""
        pid = _to_int_id(plan_id)
        now = _now()
        res = await self._cases.insert(
            {
                "plan_id": pid,
                "scenario_id": scenario_id,
                "status": status,
                "actual_result": actual_result,
                "notes": notes,
                "evidence": evidence,
                "executed_at": now,
            },
            user_id=_SYSTEM_USER,
        )
        await self._touch_plan(pid, now)
        return {
            "result_id": int(res.returned_id) if res.returned_id is not None else 0,
            "scenario_id": scenario_id,
            "status": status,
            "executed_at": now,
        }

    async def get_scenarios(self, plan_id: str | int) -> list[dict[str, Any]]:
        """Lista cenários de um plano com o status mais recente (por executed_at).

        O LEFT JOIN LATERAL legado vira agregação em Python: para cada cenário, o
        ``last_status`` é o status do test_case mais recente (maior ``executed_at``).
        """
        pid = _to_int_id(plan_id)
        scenarios = (
            await self._scenarios.find(
                where={"plan_id": pid},
                order_by=[
                    Sort(column="category", direction=SortDirection.ASC),
                    Sort(column="priority", direction=SortDirection.ASC),
                ],
            )
        ).rows()

        # Último status por cenário: ordena os cases por executed_at e guarda o último.
        cases = sorted(await self._cases_for(pid), key=lambda c: c.get("executed_at") or "")
        last_status: dict[Any, Any] = {}
        for case in cases:
            last_status[case["scenario_id"]] = case.get("status")

        out: list[dict[str, Any]] = []
        for scenario in scenarios:
            shaped = _jsonable(scenario)
            shaped["last_status"] = last_status.get(scenario["id"])
            out.append(shaped)
        return out

    # ─────────────────────────────────────────────────────────────────────── #
    # CHECKLISTS
    # ─────────────────────────────────────────────────────────────────────── #

    async def create_checklist(
        self,
        title: str,
        checklist_type: str,
        items: list[dict[str, Any]],
        plan_id: str | int | None = None,
    ) -> dict[str, Any]:
        """Cria nova checklist (cabeçalho em ``checklists`` + N ``checklist_items``)."""
        now = _now()
        plan_id_int = _to_int_id(plan_id) if plan_id is not None else None
        res = await self._checklists.insert(
            {
                "title": title,
                "checklist_type": checklist_type,
                "plan_id": plan_id_int,
                "created_at": now,
            },
            user_id=_SYSTEM_USER,
        )
        checklist_id = str(res.returned_id) if res.returned_id is not None else "0"

        for i, item in enumerate(items):
            await self._items.insert(
                {
                    "checklist_id": checklist_id,
                    "order_num": i + 1,
                    "description": item["description"],
                    "required": int(bool(item.get("required", True))),
                    "category": item.get("category"),
                },
                user_id=_SYSTEM_USER,
            )

        return {
            "checklist_id": checklist_id,
            "title": title,
            "type": checklist_type,
            "items_count": len(items),
        }

    async def start_run(self, checklist_id: str, executor: str | None = None) -> dict[str, Any]:
        """Inicia execução de checklist."""
        run_id = _new_id("run")
        now = _now()
        await self._runs.insert(
            {
                "run_id": run_id,
                "checklist_id": checklist_id,
                "status": "in_progress",
                "executor": executor,
                "started_at": now,
            },
            user_id=_SYSTEM_USER,
        )
        items = (
            await self._items.find(
                where={"checklist_id": checklist_id},
                order_by=[Sort(column="order_num", direction=SortDirection.ASC)],
            )
        ).rows()
        return {
            "run_id": run_id,
            "checklist_id": checklist_id,
            "items": [_jsonable(i) for i in items],
        }

    async def check_item(
        self, run_id: str, item_id: int, status: str, notes: str | None = None
    ) -> dict[str, Any]:
        """Registra resultado de item da checklist (upsert por chave natural composta)."""
        now = _now()
        await self._results.upsert(
            {
                "run_id": run_id,
                "item_id": item_id,
                "status": status,
                "notes": notes,
                "checked_at": now,
            },
            conflict_columns=["run_id", "item_id"],
            user_id=_SYSTEM_USER,
        )

        run_rows = (await self._runs.find(where={"run_id": run_id}, limit=1)).rows()
        if not run_rows:
            return {"run_id": run_id, "item_id": item_id, "status": status, "checked_at": now}
        checklist_id = run_rows[0]["checklist_id"]

        # Auto-completa a run quando todos os itens required foram verificados.
        items = (await self._items.find(where={"checklist_id": checklist_id})).rows()
        required_ids = {i["id"] for i in items if i.get("required")}
        results = (await self._results.find(where={"run_id": run_id})).rows()
        checked_required = len(
            {
                r["item_id"]
                for r in results
                if r["item_id"] in required_ids and r.get("status") in _DONE_STATUSES
            }
        )
        if checked_required >= len(required_ids):
            await self._runs.update_where(
                {"run_id": run_id},
                {"status": "completed", "completed_at": now},
                user_id=_SYSTEM_USER,
            )

        return {"run_id": run_id, "item_id": item_id, "status": status, "checked_at": now}

    async def get_run_status(self, run_id: str) -> dict[str, Any]:
        """Retorna status da execução da checklist (itens × resultados + summary)."""
        run_rows = (await self._runs.find(where={"run_id": run_id}, limit=1)).rows()
        if not run_rows:
            return {}
        run = run_rows[0]

        items = (
            await self._items.find(
                where={"checklist_id": run["checklist_id"]},
                order_by=[Sort(column="order_num", direction=SortDirection.ASC)],
            )
        ).rows()
        results = {r["item_id"]: r for r in (await self._results.find(where={"run_id": run_id})).rows()}

        enriched: list[dict[str, Any]] = []
        for item in items:
            res = results.get(item["id"])
            shaped = _jsonable(item)
            shaped["result_status"] = res.get("status") if res else None
            shaped["notes"] = res.get("notes") if res else None
            enriched.append(shaped)

        passed = sum(1 for i in enriched if i.get("result_status") == "passed")
        failed = sum(1 for i in enriched if i.get("result_status") == "failed")
        pending = sum(1 for i in enriched if not i.get("result_status"))

        return {
            **_jsonable(run),
            "items": enriched,
            "summary": {"passed": passed, "failed": failed, "pending": pending},
        }

    # ─────────────────────────────────────────────────────────────────────── #
    # FINDINGS / BUG REPORTS
    # ─────────────────────────────────────────────────────────────────────── #

    async def add_finding(
        self,
        plan_id: str | int,
        severity: str,
        title: str,
        description: str,
        evidence: str | None = None,
    ) -> dict[str, Any]:
        """Adiciona bug report/finding vinculado ao plano."""
        pid = _to_int_id(plan_id)
        now = _now()
        res = await self._bugs.insert(
            {
                "plan_id": pid,
                "severity": severity,
                "title": title,
                "description": description,
                "evidence": evidence,
                "status": "open",
                "created_at": now,
            },
            user_id=_SYSTEM_USER,
        )
        await self._touch_plan(pid, now)
        return {
            "finding_id": int(res.returned_id) if res.returned_id is not None else 0,
            "plan_id": plan_id,
            "severity": severity,
            "title": title,
        }

    # ─────────────────────────────────────────────────────────────────────── #
    # VALIDATION
    # ─────────────────────────────────────────────────────────────────────── #

    async def double_check(self, plan_id: str | int) -> dict[str, Any]:
        """Validação completa do plano antes do ship."""
        pid = _to_int_id(plan_id)
        all_scenarios = (await self._scenarios.find(where={"plan_id": pid})).rows()
        scenario_by_id = {s["id"]: s for s in all_scenarios}

        cases = await self._cases_for(pid)
        executed_ids = {c["scenario_id"] for c in cases}
        not_executed = [s for s in all_scenarios if s["id"] not in executed_ids]

        # Cenários com falha (test_case status=failed), ordenados por id DESC.
        failed: list[dict[str, Any]] = []
        for case in sorted(cases, key=lambda c: c.get("id") or 0, reverse=True):
            if case.get("status") != "failed":
                continue
            scenario = scenario_by_id.get(case["scenario_id"])
            if scenario is None:
                continue
            merged = _jsonable(scenario)
            merged["actual_result"] = case.get("actual_result")
            merged["notes"] = case.get("notes")
            failed.append(merged)

        # Findings abertos, ordenados por severidade.
        open_findings = sorted(
            (await self._bugs.find(where={"plan_id": pid, "status": "open"})).rows(),
            key=lambda f: _SEVERITY_RANK.get(f.get("severity"), 4),
        )
        critical_count = sum(1 for f in open_findings if f.get("severity") == "critical")

        return {
            "plan_id": plan_id,
            "not_executed": [
                {
                    "id": s["id"],
                    "name": s.get("name"),
                    "category": s.get("category"),
                    "priority": s.get("priority"),
                }
                for s in not_executed
            ],
            "failed_scenarios": failed,
            "open_findings": [_jsonable(f) for f in open_findings],
            "summary": {
                "total_scenarios": len(all_scenarios),
                "not_executed_count": len(not_executed),
                "failed_count": len(failed),
                "open_findings_count": len(open_findings),
                "critical_findings": critical_count,
                "ready_to_ship": len(not_executed) == 0 and len(failed) == 0 and critical_count == 0,
            },
        }

    async def get_validation_status(self, plan_id: str | int) -> dict[str, Any]:
        """Status de validação/qualidade do plano."""
        pid = _to_int_id(plan_id)
        plan = await self._plan_row(pid)
        if plan is None:
            return {}

        total = await self._scenarios.count(where={"plan_id": pid})

        cases = await self._cases_for(pid)
        passed = len({c["scenario_id"] for c in cases if c.get("status") == "passed"})
        failed = len({c["scenario_id"] for c in cases if c.get("status") == "failed"})
        blocked = len({c["scenario_id"] for c in cases if c.get("status") == "blocked"})

        executed = passed + failed + blocked
        coverage_pct = round((executed / total * 100), 1) if total > 0 else 0.0
        pass_rate = round((passed / executed * 100), 1) if executed > 0 else 0.0

        findings_by_severity: dict[str, int] = {}
        for finding in (await self._bugs.find(where={"plan_id": pid, "status": "open"})).rows():
            sev = finding.get("severity")
            if sev is not None:
                findings_by_severity[sev] = findings_by_severity.get(sev, 0) + 1

        grade = _grade(coverage_pct, pass_rate, findings_by_severity)

        return {
            "plan_id": plan_id,
            "title": plan.get("title"),
            "status": plan.get("status"),
            "scenarios": {
                "total": total,
                "passed": passed,
                "failed": failed,
                "blocked": blocked,
                "not_executed": total - executed,
            },
            "coverage_pct": coverage_pct,
            "pass_rate": pass_rate,
            "findings_by_severity": findings_by_severity,
            "grade": grade,
            "ready_to_ship": coverage_pct >= 80
            and pass_rate >= 90
            and not findings_by_severity.get("critical"),
        }
