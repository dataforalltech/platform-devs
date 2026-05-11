from __future__ import annotations

import json
import sqlite3
import threading
import os
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


DEFAULT_GATES: dict[str, list[str]] = {
    "dev": ["audit_compliance"],
    "homol": ["qa_tests", "pr_approved", "audit_compliance"],
    "prod": ["qa_tests", "security_scan", "pr_approved", "health_check", "audit_compliance"],
}

VALID_ENVS = {"dev", "homol", "prod", "blocked", "rollback"}
VALID_GATE_TYPES = {"qa_tests", "security_scan", "pr_approved", "health_check", "manual_approval", "audit_compliance"}


class PipelineStore:
    def __init__(self, db_path: str = ":memory:") -> None:
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._con = sqlite3.connect(db_path, check_same_thread=False, isolation_level=None)
        self._con.row_factory = sqlite3.Row
        self._con.execute("PRAGMA journal_mode=WAL")
        self._lock = threading.Lock()
        self._migrate()

        # Initialize PostgreSQL sync layer
        self._postgres_sync = None
        if os.getenv("POSTGRES_SYNC_ENABLED", "false").lower() == "true":
            try:
                from db.postgres_sync import PipelinePostgresSync
                postgres_config = {
                    "host": os.getenv("POSTGRES_HOST", "claude-dev"),
                    "port": int(os.getenv("POSTGRES_PORT", "5432")),
                    "user": os.getenv("POSTGRES_USER", "postgres"),
                    "password": os.getenv("POSTGRES_PASSWORD", "postgres_password_local_dev"),
                    "database": os.getenv("POSTGRES_DB", "app"),
                }
                self._postgres_sync = PipelinePostgresSync(postgres_config, enabled=True)
                _log.info("✅ PipelineStore: PostgreSQL sync enabled")
            except Exception as e:
                _log.warning(f"⚠️  PipelineStore: PostgreSQL sync disabled: {e}")

    def _migrate(self) -> None:
        self._con.executescript("""
            CREATE TABLE IF NOT EXISTS pipelines (
                service         TEXT PRIMARY KEY,
                repo            TEXT NOT NULL,
                base_branch     TEXT NOT NULL DEFAULT 'develop',
                current_env     TEXT NOT NULL DEFAULT 'dev',
                current_version TEXT,
                blocked         INTEGER NOT NULL DEFAULT 0,
                block_reason    TEXT,
                blocked_by      TEXT,
                blocked_at      TEXT,
                gates_config    TEXT NOT NULL DEFAULT '{}',
                registered_at   TEXT NOT NULL,
                updated_at      TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS promotions (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                service        TEXT NOT NULL,
                from_env       TEXT NOT NULL,
                to_env         TEXT NOT NULL,
                promoted_by    TEXT NOT NULL,
                reason         TEXT,
                gates_snapshot TEXT,
                deploy_ref     TEXT,
                pr_number      INTEGER,
                pr_url         TEXT,
                approved_by    TEXT,
                approved_at    TEXT,
                status         TEXT NOT NULL DEFAULT 'pending',
                created_at     TEXT NOT NULL,
                completed_at   TEXT
            );

            CREATE TABLE IF NOT EXISTS gates (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                service      TEXT NOT NULL,
                env          TEXT NOT NULL,
                gate_type    TEXT NOT NULL,
                passed       INTEGER NOT NULL,
                details      TEXT,
                evaluated_by TEXT,
                evaluated_at TEXT NOT NULL,
                UNIQUE(service, env, gate_type)
            );
        """)

    # ── Pipelines ──────────────────────────────────────────────────────────── #

    def register_pipeline(self, service: str, repo: str, base_branch: str = "develop") -> dict:
        with self._lock:
            now = _now()
            existing = self._con.execute(
                "SELECT service FROM pipelines WHERE service=?", (service,)
            ).fetchone()
            default_config = json.dumps(DEFAULT_GATES)
            if existing is None:
                self._con.execute(
                    """INSERT INTO pipelines
                       (service, repo, base_branch, current_env, blocked,
                        gates_config, registered_at, updated_at)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (service, repo, base_branch, "dev", 0, default_config, now, now),
                )
                action = "created"
            else:
                self._con.execute(
                    "UPDATE pipelines SET repo=?, base_branch=?, updated_at=? WHERE service=?",
                    (repo, base_branch, now, service),
                )
                action = "updated"
            row = self._con.execute(
                "SELECT * FROM pipelines WHERE service=?", (service,)
            ).fetchone()
            result = {"action": action, "pipeline": _pipeline_row(row)}

        # Sync to PostgreSQL (outside lock)
        if self._postgres_sync:
            try:
                pipeline_data = result["pipeline"]
                self._postgres_sync.sync_pipeline_registered(pipeline_data)
            except Exception as e:
                _log.warning(f"Failed to sync pipeline registered to PostgreSQL: {e}")

        return result

    def get_pipeline(self, service: str) -> dict | None:
        with self._lock:
            row = self._con.execute(
                "SELECT * FROM pipelines WHERE service=?", (service,)
            ).fetchone()
            if row is None:
                return None
            pipeline = _pipeline_row(row)
            promotions = self._con.execute(
                "SELECT * FROM promotions WHERE service=? ORDER BY created_at DESC LIMIT 10",
                (service,),
            ).fetchall()
            pipeline["recent_promotions"] = [dict(p) for p in promotions]
            return pipeline

    def list_pipelines(
        self, env: str | None = None, status: str | None = None
    ) -> list[dict]:
        with self._lock:
            query = "SELECT * FROM pipelines WHERE 1=1"
            params: list[Any] = []
            if env:
                query += " AND current_env=?"
                params.append(env)
            if status == "blocked":
                query += " AND blocked=1"
            elif status == "active":
                query += " AND blocked=0"
            query += " ORDER BY service"
            rows = self._con.execute(query, params).fetchall()
            return [_pipeline_row(r) for r in rows]

    def update_pipeline_env(
        self,
        service: str,
        env: str,
        version: str | None = None,
    ) -> None:
        with self._lock:
            now = _now()
            self._con.execute(
                "UPDATE pipelines SET current_env=?, current_version=?, updated_at=? WHERE service=?",
                (env, version, now, service),
            )

        # Sync to PostgreSQL
        if self._postgres_sync:
            try:
                self._postgres_sync.sync_pipeline_env_updated(service, env, version)
            except Exception as e:
                _log.warning(f"Failed to sync pipeline env update to PostgreSQL: {e}")

    def block_pipeline(self, service: str, reason: str, blocked_by: str) -> dict:
        with self._lock:
            now = _now()
            self._con.execute(
                """UPDATE pipelines
                   SET blocked=1, block_reason=?, blocked_by=?, blocked_at=?, updated_at=?
                   WHERE service=?""",
                (reason, blocked_by, now, now, service),
            )
            row = self._con.execute(
                "SELECT * FROM pipelines WHERE service=?", (service,)
            ).fetchone()
            result = _pipeline_row(row) if row else {}

        # Sync to PostgreSQL
        if self._postgres_sync:
            try:
                self._postgres_sync.sync_pipeline_blocked(service, reason, blocked_by)
            except Exception as e:
                _log.warning(f"Failed to sync pipeline blocked to PostgreSQL: {e}")

        return result

    def set_gates_config(self, service: str, gates_required: dict) -> dict:
        with self._lock:
            now = _now()
            self._con.execute(
                "UPDATE pipelines SET gates_config=?, updated_at=? WHERE service=?",
                (json.dumps(gates_required), now, service),
            )
            row = self._con.execute(
                "SELECT * FROM pipelines WHERE service=?", (service,)
            ).fetchone()
            return _pipeline_row(row) if row else {}

    # ── Promotions ─────────────────────────────────────────────────────────── #

    def add_promotion(
        self,
        service: str,
        from_env: str,
        to_env: str,
        promoted_by: str,
        reason: str | None,
        gates_snapshot: dict,
        deploy_ref: str | None,
        status: str,
        pr_number: int | None = None,
        pr_url: str | None = None,
    ) -> int:
        with self._lock:
            now = _now()
            cur = self._con.execute(
                """INSERT INTO promotions
                   (service, from_env, to_env, promoted_by, reason,
                    gates_snapshot, deploy_ref, pr_number, pr_url, status, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    service, from_env, to_env, promoted_by, reason,
                    json.dumps(gates_snapshot), deploy_ref,
                    pr_number, pr_url, status, now,
                ),
            )
            promotion_id = cur.lastrowid

        # Sync to PostgreSQL
        if self._postgres_sync:
            try:
                promotion_data = {
                    'service': service,
                    'from_env': from_env,
                    'to_env': to_env,
                    'promoted_by': promoted_by,
                    'reason': reason,
                    'gates_snapshot': gates_snapshot,
                    'deploy_ref': deploy_ref,
                    'pr_number': pr_number,
                    'pr_url': pr_url,
                    'status': status,
                }
                self._postgres_sync.sync_promotion_created(promotion_data)
            except Exception as e:
                _log.warning(f"Failed to sync promotion to PostgreSQL: {e}")

        return promotion_id  # type: ignore[return-value]

    def complete_promotion(self, promotion_id: int, status: str) -> None:
        with self._lock:
            completed_at = _now()
            self._con.execute(
                "UPDATE promotions SET status=?, completed_at=? WHERE id=?",
                (status, completed_at, promotion_id),
            )

        # Sync to PostgreSQL
        if self._postgres_sync:
            try:
                self._postgres_sync.sync_promotion_completed(promotion_id, status, completed_at)
            except Exception as e:
                _log.warning(f"Failed to sync promotion completed to PostgreSQL: {e}")

    def approve_promotion(self, promotion_id: int, approved_by: str) -> dict | None:
        with self._lock:
            now = _now()
            self._con.execute(
                "UPDATE promotions SET approved_by=?, approved_at=?, status='approved', completed_at=? WHERE id=?",
                (approved_by, now, now, promotion_id),
            )
            row = self._con.execute(
                "SELECT * FROM promotions WHERE id=?", (promotion_id,)
            ).fetchone()
            result = dict(row) if row else None

        # Sync to PostgreSQL
        if result and self._postgres_sync:
            try:
                self._postgres_sync.sync_promotion_approved(promotion_id, approved_by, now)
            except Exception as e:
                _log.warning(f"Failed to sync promotion approved to PostgreSQL: {e}")

        return result

    def get_promotion(self, promotion_id: int) -> dict | None:
        with self._lock:
            row = self._con.execute(
                "SELECT * FROM promotions WHERE id=?", (promotion_id,)
            ).fetchone()
            return dict(row) if row else None

    def get_promotion_history(
        self, service: str | None = None, limit: int = 20
    ) -> list[dict]:
        with self._lock:
            if service:
                rows = self._con.execute(
                    "SELECT * FROM promotions WHERE service=? ORDER BY created_at DESC LIMIT ?",
                    (service, limit),
                ).fetchall()
            else:
                rows = self._con.execute(
                    "SELECT * FROM promotions ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]

    # ── Gates ──────────────────────────────────────────────────────────────── #

    def upsert_gate(
        self,
        service: str,
        env: str,
        gate_type: str,
        passed: bool,
        details: str | None = None,
        evaluated_by: str | None = None,
    ) -> dict:
        with self._lock:
            now = _now()
            self._con.execute(
                """INSERT INTO gates (service, env, gate_type, passed, details, evaluated_by, evaluated_at)
                   VALUES (?,?,?,?,?,?,?)
                   ON CONFLICT(service, env, gate_type) DO UPDATE SET
                       passed=excluded.passed,
                       details=excluded.details,
                       evaluated_by=excluded.evaluated_by,
                       evaluated_at=excluded.evaluated_at""",
                (service, env, gate_type, 1 if passed else 0, details, evaluated_by, now),
            )
            row = self._con.execute(
                "SELECT * FROM gates WHERE service=? AND env=? AND gate_type=?",
                (service, env, gate_type),
            ).fetchone()
            result = dict(row) if row else {}

        # Sync to PostgreSQL
        if self._postgres_sync:
            try:
                details_dict = json.loads(details) if isinstance(details, str) else details
                self._postgres_sync.sync_gate_evaluated(service, env, gate_type, passed, details_dict)
            except Exception as e:
                _log.warning(f"Failed to sync gate evaluated to PostgreSQL: {e}")

        return result

    def get_gates(self, service: str, env: str) -> list[dict]:
        with self._lock:
            rows = self._con.execute(
                "SELECT * FROM gates WHERE service=? AND env=? ORDER BY gate_type",
                (service, env),
            ).fetchall()
            return [dict(r) for r in rows]

    def clear_gates(self, service: str, env: str) -> int:
        with self._lock:
            cur = self._con.execute(
                "DELETE FROM gates WHERE service=? AND env=?", (service, env)
            )
            return cur.rowcount

    def get_pipeline_overview(self) -> dict:
        with self._lock:
            rows = self._con.execute(
                "SELECT current_env, blocked, COUNT(*) as cnt FROM pipelines GROUP BY current_env, blocked"
            ).fetchall()
            overview: dict[str, Any] = {}
            total = 0
            for r in rows:
                env = r["current_env"]
                cnt = r["cnt"]
                total += cnt
                if env not in overview:
                    overview[env] = {"total": 0, "blocked": 0, "active": 0}
                overview[env]["total"] += cnt
                if r["blocked"]:
                    overview[env]["blocked"] += cnt
                else:
                    overview[env]["active"] += cnt

            pending_gates = self._con.execute(
                """SELECT service, env, COUNT(*) as failed
                   FROM gates WHERE passed=0 GROUP BY service, env"""
            ).fetchall()
            return {
                "total_services": total,
                "by_env": overview,
                "services_with_failed_gates": [dict(r) for r in pending_gates],
            }

    def close(self) -> None:
        self._con.close()


def _pipeline_row(row: sqlite3.Row) -> dict:  # type: ignore[type-arg]
    d = dict(row)
    if "gates_config" in d and isinstance(d["gates_config"], str):
        try:
            d["gates_config"] = json.loads(d["gates_config"])
        except (json.JSONDecodeError, TypeError):
            d["gates_config"] = {}
    return d
