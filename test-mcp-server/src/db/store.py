"""TestStore — persistência SQLite thread-safe para planos, cenários, checklists e findings."""

from __future__ import annotations

import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class TestStore:
    def __init__(self, db_path: str) -> None:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    # ── Internals ──────────────────────────────────────────────────────────── #

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS test_plans (
                    id          TEXT PRIMARY KEY,
                    title       TEXT NOT NULL,
                    scope       TEXT NOT NULL,
                    feature     TEXT,
                    status      TEXT NOT NULL DEFAULT 'active',
                    created_at  TEXT NOT NULL,
                    updated_at  TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS scenarios (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    plan_id         TEXT NOT NULL REFERENCES test_plans(id),
                    name            TEXT NOT NULL,
                    category        TEXT NOT NULL,
                    priority        TEXT NOT NULL DEFAULT 'medium',
                    preconditions   TEXT,
                    steps           TEXT NOT NULL,
                    expected_result TEXT NOT NULL,
                    created_at      TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS scenario_results (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    plan_id         TEXT NOT NULL REFERENCES test_plans(id),
                    scenario_id     INTEGER NOT NULL REFERENCES scenarios(id),
                    status          TEXT NOT NULL DEFAULT 'pending',
                    actual_result   TEXT,
                    notes           TEXT,
                    evidence        TEXT,
                    executed_at     TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS checklists (
                    id          TEXT PRIMARY KEY,
                    title       TEXT NOT NULL,
                    type        TEXT NOT NULL,
                    plan_id     TEXT REFERENCES test_plans(id),
                    created_at  TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS checklist_items (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    checklist_id    TEXT NOT NULL REFERENCES checklists(id),
                    order_num       INTEGER NOT NULL,
                    description     TEXT NOT NULL,
                    required        INTEGER NOT NULL DEFAULT 1,
                    category        TEXT
                );

                CREATE TABLE IF NOT EXISTS checklist_runs (
                    id              TEXT PRIMARY KEY,
                    checklist_id    TEXT NOT NULL REFERENCES checklists(id),
                    status          TEXT NOT NULL DEFAULT 'in_progress',
                    executor        TEXT,
                    started_at      TEXT NOT NULL,
                    completed_at    TEXT
                );

                CREATE TABLE IF NOT EXISTS checklist_results (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id      TEXT NOT NULL REFERENCES checklist_runs(id),
                    item_id     INTEGER NOT NULL REFERENCES checklist_items(id),
                    status      TEXT NOT NULL,
                    notes       TEXT,
                    checked_at  TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS findings (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    plan_id     TEXT NOT NULL REFERENCES test_plans(id),
                    severity    TEXT NOT NULL,
                    title       TEXT NOT NULL,
                    description TEXT NOT NULL,
                    evidence    TEXT,
                    status      TEXT NOT NULL DEFAULT 'open',
                    created_at  TEXT NOT NULL
                );
            """)

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _new_id(self, prefix: str = "plan") -> str:
        return f"{prefix}_{uuid.uuid4().hex[:8]}"

    # ── Test Plans ─────────────────────────────────────────────────────────── #

    def create_plan(self, title: str, scope: str, feature: str | None = None) -> dict[str, Any]:
        plan_id = self._new_id("plan")
        now = self._now()
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO test_plans (id, title, scope, feature, status, created_at, updated_at) VALUES (?, ?, ?, ?, 'active', ?, ?)",
                (plan_id, title, scope, feature, now, now),
            )
        return self.get_plan(plan_id)  # type: ignore[return-value]

    def get_plan(self, plan_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM test_plans WHERE id = ?", (plan_id,)).fetchone()
            if not row:
                return None
            d = dict(row)
            d["scenarios_count"] = conn.execute(
                "SELECT COUNT(*) FROM scenarios WHERE plan_id = ?", (plan_id,)
            ).fetchone()[0]
            d["results_count"] = conn.execute(
                "SELECT COUNT(*) FROM scenario_results WHERE plan_id = ?", (plan_id,)
            ).fetchone()[0]
            d["findings_count"] = conn.execute(
                "SELECT COUNT(*) FROM findings WHERE plan_id = ?", (plan_id,)
            ).fetchone()[0]
            # Coverage stats
            pending = conn.execute(
                "SELECT COUNT(DISTINCT scenario_id) FROM scenario_results WHERE plan_id = ? AND status = 'pending'", (plan_id,)
            ).fetchone()[0]
            passed = conn.execute(
                "SELECT COUNT(DISTINCT scenario_id) FROM scenario_results WHERE plan_id = ? AND status = 'passed'", (plan_id,)
            ).fetchone()[0]
            failed = conn.execute(
                "SELECT COUNT(DISTINCT scenario_id) FROM scenario_results WHERE plan_id = ? AND status = 'failed'", (plan_id,)
            ).fetchone()[0]
            d["coverage"] = {"passed": passed, "failed": failed, "pending": pending}
            return d

    def list_plans(self, status: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            query = "SELECT * FROM test_plans WHERE 1=1"
            params: list[Any] = []
            if status:
                query += " AND status = ?"
                params.append(status)
            query += " ORDER BY updated_at DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(query, params).fetchall()
            result = []
            for row in rows:
                d = dict(row)
                d["scenarios_count"] = conn.execute(
                    "SELECT COUNT(*) FROM scenarios WHERE plan_id = ?", (d["id"],)
                ).fetchone()[0]
                result.append(d)
            return result

    # ── Scenarios ──────────────────────────────────────────────────────────── #

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
        now = self._now()
        with self._lock, self._connect() as conn:
            result = conn.execute(
                "INSERT INTO scenarios (plan_id, name, category, priority, preconditions, steps, expected_result, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (plan_id, name, category, priority, preconditions, steps, expected_result, now),
            )
            conn.execute("UPDATE test_plans SET updated_at = ? WHERE id = ?", (now, plan_id))
            scenario_id = result.lastrowid
        return {"scenario_id": scenario_id, "plan_id": plan_id, "name": name, "category": category, "priority": priority}

    def record_result(
        self,
        plan_id: str,
        scenario_id: int,
        status: str,
        actual_result: str | None = None,
        notes: str | None = None,
        evidence: str | None = None,
    ) -> dict[str, Any]:
        now = self._now()
        with self._lock, self._connect() as conn:
            result = conn.execute(
                "INSERT INTO scenario_results (plan_id, scenario_id, status, actual_result, notes, evidence, executed_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (plan_id, scenario_id, status, actual_result, notes, evidence, now),
            )
            conn.execute("UPDATE test_plans SET updated_at = ? WHERE id = ?", (now, plan_id))
            return {"result_id": result.lastrowid, "scenario_id": scenario_id, "status": status, "executed_at": now}

    def get_scenarios(self, plan_id: str) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT s.*, r.status as last_status FROM scenarios s LEFT JOIN (SELECT scenario_id, status FROM scenario_results WHERE plan_id = ? ORDER BY id DESC) r ON s.id = r.scenario_id WHERE s.plan_id = ? GROUP BY s.id ORDER BY s.category, s.priority",
                (plan_id, plan_id),
            ).fetchall()
            return [dict(r) for r in rows]

    # ── Checklists ─────────────────────────────────────────────────────────── #

    def create_checklist(
        self,
        title: str,
        checklist_type: str,
        items: list[dict[str, Any]],
        plan_id: str | None = None,
    ) -> dict[str, Any]:
        checklist_id = self._new_id("chk")
        now = self._now()
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO checklists (id, title, type, plan_id, created_at) VALUES (?, ?, ?, ?, ?)",
                (checklist_id, title, checklist_type, plan_id, now),
            )
            for i, item in enumerate(items):
                conn.execute(
                    "INSERT INTO checklist_items (checklist_id, order_num, description, required, category) VALUES (?, ?, ?, ?, ?)",
                    (checklist_id, i + 1, item["description"], int(item.get("required", True)), item.get("category")),
                )
        return {"checklist_id": checklist_id, "title": title, "type": checklist_type, "items_count": len(items)}

    def start_run(self, checklist_id: str, executor: str | None = None) -> dict[str, Any]:
        run_id = self._new_id("run")
        now = self._now()
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO checklist_runs (id, checklist_id, status, executor, started_at) VALUES (?, ?, 'in_progress', ?, ?)",
                (run_id, checklist_id, executor, now),
            )
            items = conn.execute(
                "SELECT * FROM checklist_items WHERE checklist_id = ? ORDER BY order_num", (checklist_id,)
            ).fetchall()
        return {"run_id": run_id, "checklist_id": checklist_id, "items": [dict(i) for i in items]}

    def check_item(self, run_id: str, item_id: int, status: str, notes: str | None = None) -> dict[str, Any]:
        now = self._now()
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO checklist_results (run_id, item_id, status, notes, checked_at) VALUES (?, ?, ?, ?, ?)",
                (run_id, item_id, status, notes, now),
            )
            # Check if all required items are done
            run = conn.execute("SELECT checklist_id FROM checklist_runs WHERE id = ?", (run_id,)).fetchone()
            total_required = conn.execute(
                "SELECT COUNT(*) FROM checklist_items WHERE checklist_id = ? AND required = 1",
                (run["checklist_id"],),
            ).fetchone()[0]
            checked_required = conn.execute(
                "SELECT COUNT(*) FROM checklist_results cr JOIN checklist_items ci ON cr.item_id = ci.id WHERE cr.run_id = ? AND ci.required = 1 AND cr.status IN ('passed', 'failed', 'na')",
                (run_id,),
            ).fetchone()[0]
            if checked_required >= total_required:
                conn.execute(
                    "UPDATE checklist_runs SET status = 'completed', completed_at = ? WHERE id = ?",
                    (now, run_id),
                )
        return {"run_id": run_id, "item_id": item_id, "status": status, "checked_at": now}

    def get_run_status(self, run_id: str) -> dict[str, Any]:
        with self._lock, self._connect() as conn:
            run = conn.execute("SELECT * FROM checklist_runs WHERE id = ?", (run_id,)).fetchone()
            if not run:
                return {}
            items = conn.execute(
                "SELECT ci.*, cr.status as result_status, cr.notes FROM checklist_items ci LEFT JOIN checklist_results cr ON ci.id = cr.item_id AND cr.run_id = ? WHERE ci.checklist_id = ? ORDER BY ci.order_num",
                (run_id, run["checklist_id"]),
            ).fetchall()
            passed = sum(1 for i in items if i["result_status"] == "passed")
            failed = sum(1 for i in items if i["result_status"] == "failed")
            pending = sum(1 for i in items if not i["result_status"])
            return {
                **dict(run),
                "items": [dict(i) for i in items],
                "summary": {"passed": passed, "failed": failed, "pending": pending},
            }

    # ── Findings ───────────────────────────────────────────────────────────── #

    def add_finding(
        self,
        plan_id: str,
        severity: str,
        title: str,
        description: str,
        evidence: str | None = None,
    ) -> dict[str, Any]:
        now = self._now()
        with self._lock, self._connect() as conn:
            result = conn.execute(
                "INSERT INTO findings (plan_id, severity, title, description, evidence, status, created_at) VALUES (?, ?, ?, ?, ?, 'open', ?)",
                (plan_id, severity, title, description, evidence, now),
            )
            conn.execute("UPDATE test_plans SET updated_at = ? WHERE id = ?", (now, plan_id))
            return {"finding_id": result.lastrowid, "plan_id": plan_id, "severity": severity, "title": title}

    # ── Validation ─────────────────────────────────────────────────────────── #

    def double_check(self, plan_id: str) -> dict[str, Any]:
        with self._lock, self._connect() as conn:
            all_scenarios = conn.execute(
                "SELECT * FROM scenarios WHERE plan_id = ?", (plan_id,)
            ).fetchall()
            executed_ids = {
                r["scenario_id"]
                for r in conn.execute(
                    "SELECT DISTINCT scenario_id FROM scenario_results WHERE plan_id = ?", (plan_id,)
                ).fetchall()
            }
            not_executed = [dict(s) for s in all_scenarios if s["id"] not in executed_ids]
            failed = conn.execute(
                "SELECT s.*, r.actual_result, r.notes FROM scenario_results r JOIN scenarios s ON r.scenario_id = s.id WHERE r.plan_id = ? AND r.status = 'failed' ORDER BY r.id DESC",
                (plan_id,),
            ).fetchall()
            open_findings = conn.execute(
                "SELECT * FROM findings WHERE plan_id = ? AND status = 'open' ORDER BY CASE severity WHEN 'critical' THEN 1 WHEN 'high' THEN 2 WHEN 'medium' THEN 3 ELSE 4 END",
                (plan_id,),
            ).fetchall()
            critical_count = sum(1 for f in open_findings if f["severity"] == "critical")
            return {
                "plan_id": plan_id,
                "not_executed": [{"id": s["id"], "name": s["name"], "category": s["category"], "priority": s["priority"]} for s in not_executed],
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
        with self._lock, self._connect() as conn:
            plan = conn.execute("SELECT * FROM test_plans WHERE id = ?", (plan_id,)).fetchone()
            if not plan:
                return {}
            total = conn.execute("SELECT COUNT(*) FROM scenarios WHERE plan_id = ?", (plan_id,)).fetchone()[0]
            passed = conn.execute(
                "SELECT COUNT(DISTINCT scenario_id) FROM scenario_results WHERE plan_id = ? AND status = 'passed'", (plan_id,)
            ).fetchone()[0]
            failed = conn.execute(
                "SELECT COUNT(DISTINCT scenario_id) FROM scenario_results WHERE plan_id = ? AND status = 'failed'", (plan_id,)
            ).fetchone()[0]
            blocked = conn.execute(
                "SELECT COUNT(DISTINCT scenario_id) FROM scenario_results WHERE plan_id = ? AND status = 'blocked'", (plan_id,)
            ).fetchone()[0]
            executed = passed + failed + blocked
            coverage_pct = round((executed / total * 100), 1) if total > 0 else 0.0
            pass_rate = round((passed / executed * 100), 1) if executed > 0 else 0.0
            open_findings = conn.execute(
                "SELECT severity, COUNT(*) as cnt FROM findings WHERE plan_id = ? AND status = 'open' GROUP BY severity", (plan_id,)
            ).fetchall()
            findings_by_severity = {r["severity"]: r["cnt"] for r in open_findings}
            grade = self._grade(coverage_pct, pass_rate, findings_by_severity)
            return {
                "plan_id": plan_id,
                "title": plan["title"],
                "status": plan["status"],
                "scenarios": {"total": total, "passed": passed, "failed": failed, "blocked": blocked, "not_executed": total - executed},
                "coverage_pct": coverage_pct,
                "pass_rate": pass_rate,
                "findings_by_severity": findings_by_severity,
                "grade": grade,
                "ready_to_ship": coverage_pct >= 80 and pass_rate >= 90 and not findings_by_severity.get("critical"),
            }

    @staticmethod
    def _grade(coverage: float, pass_rate: float, findings: dict) -> str:
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
