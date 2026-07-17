"""Store do qa-engineer-mcp — 100% sobre o ORM canônico (`platform_database.orm`).

Persistência tenant-scoped (resolvida credencial-zero via `for_tenant`/
`get_pool_for_tenant`, ORM-H-12) e dual-db: o mesmo código serve MySQL (banco-por-
tenant) e PostgreSQL (schema-por-tenant) — o dialeto do pool decide o SQL.

Arquitetura "o agente gera, a tool persiste": o store expõe CRUD tipado para as 5
entidades do persona (planos/casos/bugs/quality gates/artefatos). Sem SQL manual:
cada read/write cai no Repository (`find`/`insert`/`update`/`update_where`/`upsert`/
`delete_where`). A ÚNICA chave natural é `service` no quality gate (upsert por
serviço); o resto é histórico com chave surrogate `id` e soft-delete canônico.

Dados estruturados viajam como dict/list na API e são serializados em JSON (TEXT) na
persistência (dual-db safe). Convenções: `PLATFORM_CONVENTIONS` (soft-delete
`excluded=0`, auditoria `id_user_*`/`timestamp_refresh`). Como `id_user_created` é
NOT NULL sem default, todo write carimba o usuário-sistema (`_SYSTEM_USER`).
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

from platform_database.orm import Sort, SortDirection

from ..models import (
    BugReportRow,
    QaArtifactRow,
    QualityGateRow,
    TestCaseRow,
    TestPlanRow,
)
from .schema import (
    ARTIFACTS_TABLE,
    BUG_REPORTS_TABLE,
    QUALITY_GATES_TABLE,
    TEST_CASES_TABLE,
    TEST_PLANS_TABLE,
)

# Usuário-sistema carimbado nas colunas de auditoria (id_user_created/id_user_modify).
# O persona não persiste um "ator" de negócio (governança só).
_SYSTEM_USER = 0

# As colunas de tempo (create_on / timestamp_refresh) são injetadas e populadas pela
# fábrica de schema / conventions do ORM — o store nunca as escreve à mão. A ordenação
# dos históricos usa a chave surrogate `id` (monotônica), então tampouco precisa delas.

# Campos JSON serializados em TEXT, por entidade — desserializados na leitura.
_JSON_FIELDS: dict[str, tuple[str, ...]] = {
    TEST_PLANS_TABLE: ("content",),
    TEST_CASES_TABLE: ("preconditions", "steps", "test_data"),
    BUG_REPORTS_TABLE: ("steps",),
    QUALITY_GATES_TABLE: ("thresholds",),
    ARTIFACTS_TABLE: ("meta",),
}


def _dumps(value: Any) -> str | None:
    """Serializa dict/list em JSON (TEXT). ``None`` permanece ``None`` (coluna NULL)."""
    return None if value is None else json.dumps(value, ensure_ascii=False)


def _prune(record: dict[str, Any]) -> dict[str, Any]:
    """Payload de upsert com semântica de *merge*: descarta as chaves com valor ``None``.

    O ``upsert`` do ORM deriva o ``SET`` do ON DUPLICATE KEY UPDATE de TODAS as colunas
    não-chave presentes no payload (``update_columns=None``). Se um campo omitido viajar
    como ``None``, o update-path o sobrescreve com ``NULL``, apagando o valor já gravado
    numa chamada anterior. Podando os ``None`` antes do upsert, só as colunas fornecidas
    entram no INSERT e no ``SET`` — os campos omitidos preservam o valor persistido. A
    chave natural (``service``) é sempre não-``None``, então nunca é podada.
    """
    return {k: v for k, v in record.items() if v is not None}


def _jsonable(row: dict[str, Any]) -> dict[str, Any]:
    """Datetimes das colunas padrão (create_on/timestamp_refresh) -> ISO str, para o
    `json.dumps` do envelope MCP não quebrar."""
    return {k: (v.isoformat() if isinstance(v, (datetime, date)) else v) for k, v in row.items()}


def _shape(row: dict[str, Any], json_fields: tuple[str, ...]) -> dict[str, Any]:
    """Forma canônica de uma linha: datetimes -> ISO, campos JSON (TEXT) -> dict/list."""
    shaped = _jsonable(row)
    for field in json_fields:
        value = shaped.get(field)
        if isinstance(value, str):
            try:
                shaped[field] = json.loads(value)
            except (json.JSONDecodeError, TypeError):
                shaped[field] = None
    return shaped


class QAEngineerStore:
    """Store tenant-scoped: 5 repositórios ligados ao pool do tenant.

    Recebe uma ``TenantSession`` (de ``platform_database.orm.for_tenant``) e cria os
    repositórios canônicos por ela — ``require_tenant=True`` (fail-closed ORM-H-02),
    credencial-zero (a sessão nunca expõe senha/host).
    """

    def __init__(self, session: Any) -> None:
        self._plans = session.repository(TestPlanRow, table_name=TEST_PLANS_TABLE)
        self._cases = session.repository(TestCaseRow, table_name=TEST_CASES_TABLE)
        self._bugs = session.repository(BugReportRow, table_name=BUG_REPORTS_TABLE)
        self._gates = session.repository(QualityGateRow, table_name=QUALITY_GATES_TABLE)
        self._artifacts = session.repository(QaArtifactRow, table_name=ARTIFACTS_TABLE)

    # -- helpers de leitura (por id / por chave natural) ----------------------- #

    @staticmethod
    async def _by_id(repo: Any, row_id: int, json_fields: tuple[str, ...]) -> dict[str, Any] | None:
        res = await repo.find(where={"id": row_id}, limit=1)
        rows = res.rows()
        return _shape(rows[0], json_fields) if rows else None

    # -- Test Plans ------------------------------------------------------------ #

    async def save_test_plan(
        self,
        feature: str,
        content: Any,
        scope: str = "full",
        team: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        res = await self._plans.insert(
            {
                "feature": feature,
                "scope": scope,
                "team": team,
                "content": _dumps(content),
                "status": status,
            },
            user_id=_SYSTEM_USER,
        )
        new_id = int(res.returned_id) if res.returned_id is not None else 0
        row = await self._by_id(self._plans, new_id, _JSON_FIELDS[TEST_PLANS_TABLE])
        return row or {}

    async def list_test_plans(
        self, feature: str | None = None, status: str | None = None
    ) -> list[dict[str, Any]]:
        where: dict[str, Any] = {}
        if feature:
            where["feature"] = feature
        if status:
            where["status"] = status
        res = await self._plans.find(
            where=where or None,
            order_by=[Sort(column="id", direction=SortDirection.DESC)],
        )
        return [_shape(r, _JSON_FIELDS[TEST_PLANS_TABLE]) for r in res.rows()]

    async def get_test_plan(self, plan_id: int) -> dict[str, Any] | None:
        return await self._by_id(self._plans, plan_id, _JSON_FIELDS[TEST_PLANS_TABLE])

    async def update_test_plan(
        self,
        plan_id: int,
        scope: str | None = None,
        team: str | None = None,
        content: Any = None,
        status: str | None = None,
    ) -> dict[str, Any] | None:
        changes: dict[str, Any] = {}
        if scope is not None:
            changes["scope"] = scope
        if team is not None:
            changes["team"] = team
        if content is not None:
            changes["content"] = _dumps(content)
        if status is not None:
            changes["status"] = status
        if changes:
            await self._plans.update(plan_id, changes, user_id=_SYSTEM_USER)
        return await self._by_id(self._plans, plan_id, _JSON_FIELDS[TEST_PLANS_TABLE])

    async def delete_test_plan(self, plan_id: int) -> int:
        res = await self._plans.delete_where({"id": plan_id}, user_id=_SYSTEM_USER)
        return res.rowcount

    # -- Test Cases ------------------------------------------------------------ #

    async def save_test_case(
        self,
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
        res = await self._cases.insert(
            {
                "feature": feature,
                "title": title,
                "test_type": test_type,
                "priority": priority,
                "preconditions": _dumps(preconditions),
                "steps": _dumps(steps),
                "expected_result": expected_result,
                "test_data": _dumps(test_data),
                "status": status,
            },
            user_id=_SYSTEM_USER,
        )
        new_id = int(res.returned_id) if res.returned_id is not None else 0
        row = await self._by_id(self._cases, new_id, _JSON_FIELDS[TEST_CASES_TABLE])
        return row or {}

    async def list_test_cases(
        self,
        feature: str | None = None,
        test_type: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        where: dict[str, Any] = {}
        if feature:
            where["feature"] = feature
        if test_type:
            where["test_type"] = test_type
        if status:
            where["status"] = status
        res = await self._cases.find(
            where=where or None,
            order_by=[Sort(column="id", direction=SortDirection.DESC)],
        )
        return [_shape(r, _JSON_FIELDS[TEST_CASES_TABLE]) for r in res.rows()]

    async def get_test_case(self, case_id: int) -> dict[str, Any] | None:
        return await self._by_id(self._cases, case_id, _JSON_FIELDS[TEST_CASES_TABLE])

    async def update_test_case(
        self,
        case_id: int,
        title: str | None = None,
        test_type: str | None = None,
        priority: str | None = None,
        preconditions: Any = None,
        steps: Any = None,
        expected_result: str | None = None,
        test_data: Any = None,
        status: str | None = None,
    ) -> dict[str, Any] | None:
        changes: dict[str, Any] = {}
        if title is not None:
            changes["title"] = title
        if test_type is not None:
            changes["test_type"] = test_type
        if priority is not None:
            changes["priority"] = priority
        if preconditions is not None:
            changes["preconditions"] = _dumps(preconditions)
        if steps is not None:
            changes["steps"] = _dumps(steps)
        if expected_result is not None:
            changes["expected_result"] = expected_result
        if test_data is not None:
            changes["test_data"] = _dumps(test_data)
        if status is not None:
            changes["status"] = status
        if changes:
            await self._cases.update(case_id, changes, user_id=_SYSTEM_USER)
        return await self._by_id(self._cases, case_id, _JSON_FIELDS[TEST_CASES_TABLE])

    async def delete_test_case(self, case_id: int) -> int:
        res = await self._cases.delete_where({"id": case_id}, user_id=_SYSTEM_USER)
        return res.rowcount

    # -- Bug Reports ----------------------------------------------------------- #

    async def save_bug_report(
        self,
        title: str,
        severity: str,
        impact: str,
        frequency: str,
        score: float | None = None,
        steps: Any = None,
        description: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        res = await self._bugs.insert(
            {
                "title": title,
                "severity": severity,
                "impact": impact,
                "frequency": frequency,
                "steps": _dumps(steps),
                "description": description,
                "status": status,
                "score": score,
            },
            user_id=_SYSTEM_USER,
        )
        new_id = int(res.returned_id) if res.returned_id is not None else 0
        row = await self._by_id(self._bugs, new_id, _JSON_FIELDS[BUG_REPORTS_TABLE])
        return row or {}

    async def list_bug_reports(
        self, severity: str | None = None, status: str | None = None
    ) -> list[dict[str, Any]]:
        where: dict[str, Any] = {}
        if severity:
            where["severity"] = severity
        if status:
            where["status"] = status
        res = await self._bugs.find(
            where=where or None,
            order_by=[Sort(column="id", direction=SortDirection.DESC)],
        )
        return [_shape(r, _JSON_FIELDS[BUG_REPORTS_TABLE]) for r in res.rows()]

    async def get_bug_report(self, bug_id: int) -> dict[str, Any] | None:
        return await self._by_id(self._bugs, bug_id, _JSON_FIELDS[BUG_REPORTS_TABLE])

    async def update_bug_status(self, bug_id: int, status: str) -> dict[str, Any] | None:
        await self._bugs.update(bug_id, {"status": status}, user_id=_SYSTEM_USER)
        return await self._by_id(self._bugs, bug_id, _JSON_FIELDS[BUG_REPORTS_TABLE])

    async def delete_bug_report(self, bug_id: int) -> int:
        res = await self._bugs.delete_where({"id": bug_id}, user_id=_SYSTEM_USER)
        return res.rowcount

    # -- Quality Gates (upsert por chave natural `service`) -------------------- #

    async def _gate_by_service(self, service: str) -> dict[str, Any] | None:
        res = await self._gates.find(where={"service": service}, limit=1)
        rows = res.rows()
        return _shape(rows[0], _JSON_FIELDS[QUALITY_GATES_TABLE]) if rows else None

    async def set_quality_gate(
        self, service: str, thresholds: Any, status: str | None = None
    ) -> dict[str, Any]:
        await self._gates.upsert(
            _prune(
                {
                    "service": service,
                    "thresholds": _dumps(thresholds),
                    "status": status,
                }
            ),
            conflict_columns=["service"],
            user_id=_SYSTEM_USER,
        )
        row = await self._gate_by_service(service)
        return row or {}

    async def list_quality_gates(self, status: str | None = None) -> list[dict[str, Any]]:
        where: dict[str, Any] = {}
        if status:
            where["status"] = status
        res = await self._gates.find(
            where=where or None,
            order_by=[Sort(column="service", direction=SortDirection.ASC)],
        )
        return [_shape(r, _JSON_FIELDS[QUALITY_GATES_TABLE]) for r in res.rows()]

    async def get_quality_gate(self, service: str) -> dict[str, Any] | None:
        return await self._gate_by_service(service)

    async def delete_quality_gate(self, service: str) -> int:
        res = await self._gates.delete_where({"service": service}, user_id=_SYSTEM_USER)
        return res.rowcount

    # -- Artifacts (histórico append-only) ------------------------------------- #

    async def save_artifact(
        self,
        kind: str,
        target: str,
        content: str,
        framework: str | None = None,
        meta: Any = None,
    ) -> dict[str, Any]:
        res = await self._artifacts.insert(
            {
                "kind": kind,
                "target": target,
                "framework": framework,
                "content": content,
                "meta": _dumps(meta),
            },
            user_id=_SYSTEM_USER,
        )
        new_id = int(res.returned_id) if res.returned_id is not None else 0
        row = await self._by_id(self._artifacts, new_id, _JSON_FIELDS[ARTIFACTS_TABLE])
        return row or {}

    async def list_artifacts(
        self, kind: str | None = None, target: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        where: dict[str, Any] = {}
        if kind:
            where["kind"] = kind
        if target:
            where["target"] = target
        res = await self._artifacts.find(
            where=where or None,
            order_by=[Sort(column="id", direction=SortDirection.DESC)],
            limit=limit,
        )
        return [_shape(r, _JSON_FIELDS[ARTIFACTS_TABLE]) for r in res.rows()]

    async def get_artifact(self, artifact_id: int) -> dict[str, Any] | None:
        return await self._by_id(self._artifacts, artifact_id, _JSON_FIELDS[ARTIFACTS_TABLE])

    async def delete_artifact(self, artifact_id: int) -> int:
        res = await self._artifacts.delete_where({"id": artifact_id}, user_id=_SYSTEM_USER)
        return res.rowcount
