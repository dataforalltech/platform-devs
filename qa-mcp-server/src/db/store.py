from __future__ import annotations

import json
import psycopg2
import psycopg2.pool
import psycopg2.extras
import logging
from contextlib import contextmanager
import threading
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class QAStore:
    def __init__(self, db_path: str = ":memory:") -> None:
        self._pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=2,
            maxconn=10,
            dsn=os.getenv("PG_DSN", "postgresql://localhost/qa_mcp"),
        )
        self._lock = threading.Lock()
        self._migrate()

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
                    CREATE TABLE IF NOT EXISTS test_runs (
                        id          SERIAL PRIMARY KEY,
                        repo_path   TEXT,
                        run_type    TEXT NOT NULL,
                        framework   TEXT,
                        started_at  TEXT NOT NULL,
                        duration_ms INTEGER,
                        status      TEXT NOT NULL,
                        summary     TEXT NOT NULL DEFAULT '{}',
                        details     TEXT NOT NULL DEFAULT '{}'
                    );
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_runs_repo ON test_runs(repo_path, run_type, started_at DESC);
                """)

    def save_run(
        self,
        run_type: str,
        status: str,
        summary: dict,
        details: dict,
        repo_path: str | None = None,
        framework: str | None = None,
        duration_ms: int | None = None,
    ) -> int:
        with self._lock:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """INSERT INTO test_runs
                           (repo_path, run_type, framework, started_at, duration_ms, status, summary, details)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                           RETURNING id""",
                        (
                            repo_path,
                            run_type,
                            framework,
                            _now(),
                            duration_ms,
                            status,
                            json.dumps(summary),
                            json.dumps(details),
                        ),
                    )
                    run_id = cur.fetchone()[0]
                    return run_id  # type: ignore[return-value]

    def list_runs(
        self,
        repo_path: str | None = None,
        run_type: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        with self._lock:
            with self._get_conn() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    q = "SELECT * FROM test_runs WHERE 1=1"
                    params: list[Any] = []
                    if repo_path:
                        q += " AND repo_path=%s"
                        params.append(repo_path)
                    if run_type:
                        q += " AND run_type=%s"
                        params.append(run_type)
                    q += " ORDER BY started_at DESC LIMIT %s"
                    params.append(limit)
                    cur.execute(q, params)
                    rows = cur.fetchall()
                    return [
                        {
                            **dict(r),
                            "summary": json.loads(r["summary"]),
                            "details": json.loads(r["details"]),
                        }
                        for r in rows
                    ]

    def close(self) -> None:
        if self._pool:
            self._pool.closeall()
        _log.info("✅ QAStore closed: PostgreSQL pool")
