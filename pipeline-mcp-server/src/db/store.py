from __future__ import annotations

import json
import psycopg2
import psycopg2.pool
import psycopg2.extras
from contextlib import contextmanager
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
        self._pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=2,
            maxconn=10,
            dsn=os.getenv("PG_DSN", "postgresql://localhost/pipeline_mcp"),
        )
        self._lock = threading.Lock()
        self._migrate()

        # Initialize PostgreSQL sync layer (legacy)
        self._postgres_sync = None

    @contextmanager
    def _get_conn(self):
        conn = self._pool.getconn()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            self._pool.putconn(conn)

    def _migrate(self) -> None:
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
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
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS promotions (
                        id             SERIAL PRIMARY KEY,
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
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS gates (
                        id           SERIAL PRIMARY KEY,
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
            with self._get_conn() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute(
                        "SELECT service FROM pipelines WHERE service=%s", (service,)
                    )
                    existing = cur.fetchone()
                    default_config = json.dumps(DEFAULT_GATES)
                    if existing is None:
                        cur.execute(
                            """INSERT INTO pipelines
                               (service, repo, base_branch, current_env, blocked,
                                gates_config, registered_at, updated_at)
                               VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                            (service, repo, base_branch, "dev", 0, default_config, now, now),
                        )
                        action = "created"
                    else:
                        cur.execute(
                            "UPDATE pipelines SET repo=%s, base_branch=%s, updated_at=%s WHERE service=%s",
                            (repo, base_branch, now, service),
                        )
                        action = "updated"
                    cur.execute(
                        "SELECT * FROM pipelines WHERE service=%s", (service,)
                    )
                    row = cur.fetchone()
                    result = {"action": action, "pipeline": _pipeline_row(row)}

        return result

    def get_pipeline(self, service: str) -> dict | None:
        with self._lock:
            with self._get_conn() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute(
                        "SELECT * FROM pipelines WHERE service=%s", (service,)
                    )
                    row = cur.fetchone()
                    if row is None:
                        return None
                    pipeline = _pipeline_row(row)
                    cur.execute(
                        "SELECT * FROM promotions WHERE service=%s ORDER BY created_at DESC LIMIT 10",
                        (service,),
                    )
                    promotions = cur.fetchall()
                    pipeline["recent_promotions"] = [dict(p) for p in promotions]
                    return pipeline

    def list_pipelines(
        self, env: str | None = None, status: str | None = None
    ) -> list[dict]:
        with self._lock:
            with self._get_conn() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    query = "SELECT * FROM pipelines WHERE 1=1"
                    params: list[Any] = []
                    if env:
                        query += " AND current_env=%s"
                        params.append(env)
                    if status == "blocked":
                        query += " AND blocked=1"
                    elif status == "active":
                        query += " AND blocked=0"
                    query += " ORDER BY service"
                    cur.execute(query, params)
                    rows = cur.fetchall()
                    return [_pipeline_row(r) for r in rows]

    def update_pipeline_env(
        self,
        service: str,
        env: str,
        version: str | None = None,
    ) -> None:
        with self._lock:
            now = _now()
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE pipelines SET current_env=%s, current_version=%s, updated_at=%s WHERE service=%s",
                        (env, version, now, service),
                    )

    def block_pipeline(self, service: str, reason: str, blocked_by: str) -> dict:
        with self._lock:
            now = _now()
            with self._get_conn() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute(
                        """UPDATE pipelines
                           SET blocked=1, block_reason=%s, blocked_by=%s, blocked_at=%s, updated_at=%s
                           WHERE service=%s""",
                        (reason, blocked_by, now, now, service),
                    )
                    cur.execute(
                        "SELECT * FROM pipelines WHERE service=%s", (service,)
                    )
                    row = cur.fetchone()
                    result = _pipeline_row(row) if row else {}

        return result

    def set_gates_config(self, service: str, gates_required: dict) -> dict:
        with self._lock:
            now = _now()
            with self._get_conn() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute(
                        "UPDATE pipelines SET gates_config=%s, updated_at=%s WHERE service=%s",
                        (json.dumps(gates_required), now, service),
                    )
                    cur.execute(
                        "SELECT * FROM pipelines WHERE service=%s", (service,)
                    )
                    row = cur.fetchone()
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
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """INSERT INTO promotions
                           (service, from_env, to_env, promoted_by, reason,
                            gates_snapshot, deploy_ref, pr_number, pr_url, status, created_at)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                           RETURNING id""",
                        (
                            service, from_env, to_env, promoted_by, reason,
                            json.dumps(gates_snapshot), deploy_ref,
                            pr_number, pr_url, status, now,
                        ),
                    )
                    promotion_id = cur.fetchone()[0]

        return promotion_id  # type: ignore[return-value]

    def complete_promotion(self, promotion_id: int, status: str) -> None:
        with self._lock:
            completed_at = _now()
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE promotions SET status=%s, completed_at=%s WHERE id=%s",
                        (status, completed_at, promotion_id),
                    )

    def approve_promotion(self, promotion_id: int, approved_by: str) -> dict | None:
        with self._lock:
            now = _now()
            with self._get_conn() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute(
                        "UPDATE promotions SET approved_by=%s, approved_at=%s, status='approved', completed_at=%s WHERE id=%s",
                        (approved_by, now, now, promotion_id),
                    )
                    cur.execute(
                        "SELECT * FROM promotions WHERE id=%s", (promotion_id,)
                    )
                    row = cur.fetchone()
                    result = dict(row) if row else None

        return result

    def get_promotion(self, promotion_id: int) -> dict | None:
        with self._lock:
            with self._get_conn() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute(
                        "SELECT * FROM promotions WHERE id=%s", (promotion_id,)
                    )
                    row = cur.fetchone()
                    return dict(row) if row else None

    def get_promotion_history(
        self, service: str | None = None, limit: int = 20
    ) -> list[dict]:
        with self._lock:
            with self._get_conn() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    if service:
                        cur.execute(
                            "SELECT * FROM promotions WHERE service=%s ORDER BY created_at DESC LIMIT %s",
                            (service, limit),
                        )
                    else:
                        cur.execute(
                            "SELECT * FROM promotions ORDER BY created_at DESC LIMIT %s",
                            (limit,),
                        )
                    rows = cur.fetchall()
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
            with self._get_conn() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute(
                        """INSERT INTO gates (service, env, gate_type, passed, details, evaluated_by, evaluated_at)
                           VALUES (%s,%s,%s,%s,%s,%s,%s)
                           ON CONFLICT(service, env, gate_type) DO UPDATE SET
                               passed=EXCLUDED.passed,
                               details=EXCLUDED.details,
                               evaluated_by=EXCLUDED.evaluated_by,
                               evaluated_at=EXCLUDED.evaluated_at""",
                        (service, env, gate_type, 1 if passed else 0, details, evaluated_by, now),
                    )
                    cur.execute(
                        "SELECT * FROM gates WHERE service=%s AND env=%s AND gate_type=%s",
                        (service, env, gate_type),
                    )
                    row = cur.fetchone()
                    result = dict(row) if row else {}

        return result

    def get_gates(self, service: str, env: str) -> list[dict]:
        with self._lock:
            with self._get_conn() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute(
                        "SELECT * FROM gates WHERE service=%s AND env=%s ORDER BY gate_type",
                        (service, env),
                    )
                    rows = cur.fetchall()
                    return [dict(r) for r in rows]

    def clear_gates(self, service: str, env: str) -> int:
        with self._lock:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "DELETE FROM gates WHERE service=%s AND env=%s", (service, env)
                    )
                    return cur.rowcount

    def get_pipeline_overview(self) -> dict:
        with self._lock:
            with self._get_conn() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute(
                        "SELECT current_env, blocked, COUNT(*) as cnt FROM pipelines GROUP BY current_env, blocked"
                    )
                    rows = cur.fetchall()
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

                    cur.execute(
                        """SELECT service, env, COUNT(*) as failed
                           FROM gates WHERE passed=0 GROUP BY service, env"""
                    )
                    pending_gates = cur.fetchall()
                    return {
                        "total_services": total,
                        "by_env": overview,
                        "services_with_failed_gates": [dict(r) for r in pending_gates],
                    }

    def close(self) -> None:
        if self._pool:
            self._pool.closeall()


def _pipeline_row(row: dict) -> dict:
    d = dict(row) if row else {}
    if "gates_config" in d and isinstance(d["gates_config"], str):
        try:
            d["gates_config"] = json.loads(d["gates_config"])
        except (json.JSONDecodeError, TypeError):
            d["gates_config"] = {}
    return d
