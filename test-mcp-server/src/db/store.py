"""TestStore â€” persistÃªncia PostgreSQL thread-safe para planos, cenÃ¡rios, checklists e findings."""

from __future__ import annotations

import json
import logging
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

import psycopg2
import psycopg2.extras
import psycopg2.pool

from ..config.settings import TestSettings

logger = logging.getLogger(__name__)


class TestStore:
    """PostgreSQL thread-safe test store com connection pool."""

    def __init__(self, settings: TestSettings) -> None:
        self.settings = settings
        self._pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=settings.pg_min_conn,
            maxconn=settings.pg_max_conn,
            dsn=settings.pg_dsn,
        )
        logger.info(f"âœ… TestStore initialized with PostgreSQL pool ({settings.pg_min_conn}-{settings.pg_max_conn} connections)")

    @contextmanager
    def _get_conn(self):
        """Context manager para obter conexÃ£o do pool."""
        conn = self._pool.getconn()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            self._pool.putconn(conn)

    def close(self) -> None:
        """Fecha o connection pool."""
        if self._pool:
            self._pool.closeall()
            logger.info("TestStore connection pool closed")

    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ #
    # UTILITY METHODS
    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ #

    def _now(self) -> str:
        """Retorna ISO timestamp com timezone."""
        return datetime.now(timezone.utc).isoformat()

    def _new_id(self, prefix: str = "plan") -> str:
        """Gera ID Ãºnico com prefixo (usado apenas para tabelas com PK TEXT)."""
        return f"{prefix}_{uuid.uuid4().hex[:8]}"

    @staticmethod
    def _to_int_id(plan_id: str | int) -> int:
        """Converte plan_id para int â€” o banco usa INTEGER como PK em test_plans."""
        try:
            return int(plan_id)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"plan_id invÃ¡lido: {plan_id!r} â€” deve ser numÃ©rico") from exc

    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ #
    # TEST PLANS OPERATIONS
    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ #

    def create_plan(self, title: str, scope: str, feature: str | None = None) -> dict[str, Any]:
        """Cria novo plano de testes."""
        now = self._now()
        with self._get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO test_plans (title, scope, feature, status, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id, title, scope, feature, status, created_at, updated_at
                    """,
                    (title, scope, feature, "active", now, now),
                )
                row = cur.fetchone()

        return {
            "id": row["id"],
            "title": row["title"],
            "scope": row["scope"],
            "feature": row["feature"],
            "status": row["status"],
            "created_at": row["created_at"],
        }

    def get_plan(self, plan_id: str) -> dict[str, Any] | None:
        """Retorna plano completo com estatÃ­sticas."""
        pid = self._to_int_id(plan_id)
        with self._get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM test_plans WHERE id = %s",
                    (pid,),
                )
                row = cur.fetchone()
                if not row:
                    return None

                # Count scenarios
                cur.execute(
                    "SELECT COUNT(*) as cnt FROM test_scenarios WHERE plan_id = %s",
                    (pid,),
                )
                scenarios_count = cur.fetchone()["cnt"]

                # Count results
                cur.execute(
                    "SELECT COUNT(*) as cnt FROM test_cases WHERE plan_id = %s",
                    (pid,),
                )
                results_count = cur.fetchone()["cnt"]

                # Count findings
                cur.execute(
                    "SELECT COUNT(*) as cnt FROM bug_reports WHERE plan_id = %s",
                    (pid,),
                )
                findings_count = cur.fetchone()["cnt"]

                # Coverage stats
                cur.execute(
                    "SELECT COUNT(DISTINCT scenario_id) as cnt FROM test_cases WHERE plan_id = %s AND status = %s",
                    (pid, "pending"),
                )
                pending = cur.fetchone()["cnt"]

                cur.execute(
                    "SELECT COUNT(DISTINCT scenario_id) as cnt FROM test_cases WHERE plan_id = %s AND status = %s",
                    (pid, "passed"),
                )
                passed = cur.fetchone()["cnt"]

                cur.execute(
                    "SELECT COUNT(DISTINCT scenario_id) as cnt FROM test_cases WHERE plan_id = %s AND status = %s",
                    (pid, "failed"),
                )
                failed = cur.fetchone()["cnt"]

                d = dict(row)
                d["scenarios_count"] = scenarios_count
                d["results_count"] = results_count
                d["findings_count"] = findings_count
                d["coverage"] = {"passed": passed, "failed": failed, "pending": pending}
                return d

    def list_plans(self, status: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        """Lista planos de testes com filtros opcionais."""
        with self._get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                query = "SELECT * FROM test_plans WHERE 1=1"
                params: list[Any] = []

                if status:
                    query += " AND status = %s"
                    params.append(status)

                query += " ORDER BY updated_at DESC LIMIT %s"
                params.append(limit)

                cur.execute(query, params)
                rows = cur.fetchall() or []

                result = []
                for row in rows:
                    # Count scenarios for each plan
                    cur.execute(
                        "SELECT COUNT(*) as cnt FROM test_scenarios WHERE plan_id = %s",
                        (row["id"],),
                    )
                    scenarios_count = cur.fetchone()["cnt"]

                    d = dict(row)
                    d["scenarios_count"] = scenarios_count
                    result.append(d)

                return result

    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ #
    # SCENARIOS OPERATIONS
    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ #

    def add_scenario(
        self,
        plan_id: str,
        name: str,
        category: str,
        steps: str,
        expected_result: str,
        priority: str = "medium",
        preconditions: str | None = None,
    ) -> dict[str, Any]:
        """Adiciona cenÃ¡rio ao plano."""
        pid = self._to_int_id(plan_id)
        now = self._now()
        with self._get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO test_scenarios
                    (plan_id, name, category, priority, preconditions, steps, expected_result, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (pid, name, category, priority, preconditions, steps, expected_result, now),
                )
                scenario_id = cur.fetchone()["id"]

                # Update plan timestamp
                cur.execute(
                    "UPDATE test_plans SET updated_at = %s WHERE id = %s",
                    (now, pid),
                )

        return {
            "scenario_id": scenario_id,
            "plan_id": plan_id,
            "name": name,
            "category": category,
            "priority": priority,
        }

    def record_result(
        self,
        plan_id: str,
        scenario_id: int,
        status: str,
        actual_result: str | None = None,
        notes: str | None = None,
        evidence: str | None = None,
    ) -> dict[str, Any]:
        """Registra resultado de execuÃ§Ã£o de cenÃ¡rio."""
        pid = self._to_int_id(plan_id)
        now = self._now()
        with self._get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO test_cases (plan_id, scenario_id, status, actual_result, notes, evidence, executed_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (pid, scenario_id, status, actual_result, notes, evidence, now),
                )
                result_id = cur.fetchone()["id"]

                # Update plan timestamp
                cur.execute(
                    "UPDATE test_plans SET updated_at = %s WHERE id = %s",
                    (now, pid),
                )

        return {"result_id": result_id, "scenario_id": scenario_id, "status": status, "executed_at": now}

    def get_scenarios(self, plan_id: str) -> list[dict[str, Any]]:
        """Lista cenÃ¡rios de um plano com status mais recente."""
        pid = self._to_int_id(plan_id)
        with self._get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT s.*, tc.status as last_status
                    FROM test_scenarios s
                    LEFT JOIN LATERAL (
                        SELECT status FROM test_cases
                        WHERE scenario_id = s.id AND plan_id = %s
                        ORDER BY executed_at DESC LIMIT 1
                    ) tc ON true
                    WHERE s.plan_id = %s
                    ORDER BY s.category, s.priority
                    """,
                    (pid, pid),
                )
                return cur.fetchall() or []

    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ #
    # CHECKLISTS OPERATIONS
    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ #

    def create_checklist(
        self,
        title: str,
        checklist_type: str,
        items: list[dict[str, Any]],
        plan_id: str | None = None,
    ) -> dict[str, Any]:
        """Cria nova checklist."""
        now = self._now()
        # plan_id FK is INTEGER â€” convert if present
        plan_id_int = int(plan_id) if plan_id is not None else None
        with self._get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO quality_gates (title, type, plan_id, created_at)
                    VALUES (%s, %s, %s, %s)
                    RETURNING id
                    """,
                    (title, checklist_type, plan_id_int, now),
                )
                checklist_id = str(cur.fetchone()["id"])

                for i, item in enumerate(items):
                    cur.execute(
                        """
                        INSERT INTO checklist_items (checklist_id, order_num, description, required, category)
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (checklist_id, i + 1, item["description"], bool(item.get("required", True)), item.get("category")),
                    )

        return {"checklist_id": checklist_id, "title": title, "type": checklist_type, "items_count": len(items)}

    def start_run(self, checklist_id: str, executor: str | None = None) -> dict[str, Any]:
        """Inicia execuÃ§Ã£o de checklist."""
        run_id = self._new_id("run")
        now = self._now()
        with self._get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO checklist_runs (id, checklist_id, status, executor, started_at)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (run_id, checklist_id, "in_progress", executor, now),
                )

                cur.execute(
                    """
                    SELECT * FROM checklist_items
                    WHERE checklist_id = %s ORDER BY order_num
                    """,
                    (checklist_id,),
                )
                items = cur.fetchall() or []

        return {"run_id": run_id, "checklist_id": checklist_id, "items": [dict(i) for i in items]}

    def check_item(self, run_id: str, item_id: int, status: str, notes: str | None = None) -> dict[str, Any]:
        """Registra resultado de item da checklist."""
        now = self._now()
        with self._get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                # Upsert checklist result
                cur.execute(
                    """
                    INSERT INTO checklist_results (run_id, item_id, status, notes, checked_at)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (run_id, item_id) DO UPDATE
                    SET status = EXCLUDED.status, notes = EXCLUDED.notes, checked_at = EXCLUDED.checked_at
                    """,
                    (run_id, item_id, status, notes, now),
                )

                # Check if all required items are done
                cur.execute(
                    "SELECT checklist_id FROM checklist_runs WHERE id = %s",
                    (run_id,),
                )
                run = cur.fetchone()
                if not run:
                    return {"run_id": run_id, "item_id": item_id, "status": status, "checked_at": now}

                cur.execute(
                    """
                    SELECT COUNT(*) as cnt FROM checklist_items
                    WHERE checklist_id = %s AND required = true
                    """,
                    (run["checklist_id"],),
                )
                total_required = cur.fetchone()["cnt"]

                cur.execute(
                    """
                    SELECT COUNT(*) as cnt FROM checklist_results cr
                    JOIN checklist_items ci ON cr.item_id = ci.id
                    WHERE cr.run_id = %s AND ci.required = true
                    AND cr.status IN ('passed', 'failed', 'na')
                    """,
                    (run_id,),
                )
                checked_required = cur.fetchone()["cnt"]

                if checked_required >= total_required:
                    cur.execute(
                        "UPDATE checklist_runs SET status = %s, completed_at = %s WHERE id = %s",
                        ("completed", now, run_id),
                    )

        return {"run_id": run_id, "item_id": item_id, "status": status, "checked_at": now}

    def get_run_status(self, run_id: str) -> dict[str, Any]:
        """Retorna status da execuÃ§Ã£o da checklist."""
        with self._get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM checklist_runs WHERE id = %s",
                    (run_id,),
                )
                run = cur.fetchone()
                if not run:
                    return {}

                cur.execute(
                    """
                    SELECT ci.*, cr.status as result_status, cr.notes
                    FROM checklist_items ci
                    LEFT JOIN checklist_results cr ON ci.id = cr.item_id AND cr.run_id = %s
                    WHERE ci.checklist_id = %s
                    ORDER BY ci.order_num
                    """,
                    (run_id, run["checklist_id"]),
                )
                items = cur.fetchall() or []

                passed = sum(1 for i in items if i.get("result_status") == "passed")
                failed = sum(1 for i in items if i.get("result_status") == "failed")
                pending = sum(1 for i in items if not i.get("result_status"))

                return {
                    **dict(run),
                    "items": [dict(i) for i in items],
                    "summary": {"passed": passed, "failed": failed, "pending": pending},
                }

    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ #
    # FINDINGS/BUG REPORTS OPERATIONS
    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ #

    def add_finding(
        self,
        plan_id: str,
        severity: str,
        title: str,
        description: str,
        evidence: str | None = None,
    ) -> dict[str, Any]:
        """Adiciona bug report/finding."""
        pid = self._to_int_id(plan_id)
        now = self._now()
        with self._get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO bug_reports (plan_id, severity, title, description, evidence, status, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (pid, severity, title, description, evidence, "open", now),
                )
                finding_id = cur.fetchone()["id"]

                # Update plan timestamp
                cur.execute(
                    "UPDATE test_plans SET updated_at = %s WHERE id = %s",
                    (now, pid),
                )

        return {"finding_id": finding_id, "plan_id": plan_id, "severity": severity, "title": title}

    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ #
    # VALIDATION OPERATIONS
    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ #

    def double_check(self, plan_id: str) -> dict[str, Any]:
        """ValidaÃ§Ã£o completa do plano antes do ship."""
        pid = self._to_int_id(plan_id)
        with self._get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                # All scenarios
                cur.execute(
                    "SELECT * FROM test_scenarios WHERE plan_id = %s",
                    (pid,),
                )
                all_scenarios = cur.fetchall() or []

                # Executed scenario IDs
                cur.execute(
                    "SELECT DISTINCT scenario_id FROM test_cases WHERE plan_id = %s",
                    (pid,),
                )
                executed_ids = {r["scenario_id"] for r in cur.fetchall()}

                not_executed = [dict(s) for s in all_scenarios if s["id"] not in executed_ids]

                # Failed scenarios
                cur.execute(
                    """
                    SELECT s.*, tc.actual_result, tc.notes
                    FROM test_cases tc
                    JOIN test_scenarios s ON tc.scenario_id = s.id
                    WHERE tc.plan_id = %s AND tc.status = %s
                    ORDER BY tc.id DESC
                    """,
                    (pid, "failed"),
                )
                failed = cur.fetchall() or []

                # Open findings
                cur.execute(
                    """
                    SELECT * FROM bug_reports
                    WHERE plan_id = %s AND status = %s
                    ORDER BY CASE severity
                        WHEN 'critical' THEN 1
                        WHEN 'high' THEN 2
                        WHEN 'medium' THEN 3
                        ELSE 4
                    END
                    """,
                    (pid, "open"),
                )
                open_findings = cur.fetchall() or []

                critical_count = sum(1 for f in open_findings if f.get("severity") == "critical")

                return {
                    "plan_id": plan_id,
                    "not_executed": [
                        {"id": s["id"], "name": s["name"], "category": s["category"], "priority": s["priority"]}
                        for s in not_executed
                    ],
                    "failed_scenarios": [dict(f) for f in failed],
                    "open_findings": [dict(f) for f in open_findings],
                    "summary": {
                        "total_scenarios": len(all_scenarios),
                        "not_executed_count": len(not_executed),
                        "failed_count": len(failed),
                        "open_findings_count": len(open_findings),
                        "critical_findings": critical_count,
                        "ready_to_ship": len(not_executed) == 0 and len(failed) == 0 and critical_count == 0,
                    },
                }

    def get_validation_status(self, plan_id: str) -> dict[str, Any]:
        """Status de validaÃ§Ã£o/qualidade do plano."""
        pid = self._to_int_id(plan_id)
        with self._get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM test_plans WHERE id = %s",
                    (pid,),
                )
                plan = cur.fetchone()
                if not plan:
                    return {}

                cur.execute(
                    "SELECT COUNT(*) as cnt FROM test_scenarios WHERE plan_id = %s",
                    (pid,),
                )
                total = cur.fetchone()["cnt"]

                cur.execute(
                    """
                    SELECT COUNT(DISTINCT scenario_id) as cnt FROM test_cases
                    WHERE plan_id = %s AND status = %s
                    """,
                    (pid, "passed"),
                )
                passed = cur.fetchone()["cnt"]

                cur.execute(
                    """
                    SELECT COUNT(DISTINCT scenario_id) as cnt FROM test_cases
                    WHERE plan_id = %s AND status = %s
                    """,
                    (pid, "failed"),
                )
                failed = cur.fetchone()["cnt"]

                cur.execute(
                    """
                    SELECT COUNT(DISTINCT scenario_id) as cnt FROM test_cases
                    WHERE plan_id = %s AND status = %s
                    """,
                    (pid, "blocked"),
                )
                blocked = cur.fetchone()["cnt"]

                executed = passed + failed + blocked
                coverage_pct = round((executed / total * 100), 1) if total > 0 else 0.0
                pass_rate = round((passed / executed * 100), 1) if executed > 0 else 0.0

                cur.execute(
                    """
                    SELECT severity, COUNT(*) as cnt FROM bug_reports
                    WHERE plan_id = %s AND status = %s
                    GROUP BY severity
                    """,
                    (pid, "open"),
                )
                open_findings = cur.fetchall() or []
                findings_by_severity = {r["severity"]: r["cnt"] for r in open_findings}

                grade = self._grade(coverage_pct, pass_rate, findings_by_severity)

                return {
                    "plan_id": plan_id,
                    "title": plan["title"],
                    "status": plan["status"],
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
                    "ready_to_ship": coverage_pct >= 80 and pass_rate >= 90 and not findings_by_severity.get("critical"),
                }

    @staticmethod
    def _grade(coverage: float, pass_rate: float, findings: dict) -> str:
        """Calcula grade de qualidade."""
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
