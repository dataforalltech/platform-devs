from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class QAStore:
    def __init__(self, db_path: str = ":memory:") -> None:
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._con = sqlite3.connect(db_path, check_same_thread=False, isolation_level=None)
        self._con.row_factory = sqlite3.Row
        self._con.execute("PRAGMA journal_mode=WAL")
        self._lock = threading.Lock()
        self._migrate()

    def _migrate(self) -> None:
        self._con.executescript("""
            CREATE TABLE IF NOT EXISTS test_runs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                repo_path   TEXT,
                run_type    TEXT NOT NULL,
                framework   TEXT,
                started_at  TEXT NOT NULL,
                duration_ms INTEGER,
                status      TEXT NOT NULL,
                summary     TEXT NOT NULL DEFAULT '{}',
                details     TEXT NOT NULL DEFAULT '{}'
            );
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
            cur = self._con.execute(
                """INSERT INTO test_runs
                   (repo_path, run_type, framework, started_at, duration_ms, status, summary, details)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
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
            return cur.lastrowid  # type: ignore[return-value]

    def list_runs(
        self,
        repo_path: str | None = None,
        run_type: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        with self._lock:
            q = "SELECT * FROM test_runs WHERE 1=1"
            params: list[Any] = []
            if repo_path:
                q += " AND repo_path=?"
                params.append(repo_path)
            if run_type:
                q += " AND run_type=?"
                params.append(run_type)
            q += " ORDER BY started_at DESC LIMIT ?"
            params.append(limit)
            rows = self._con.execute(q, params).fetchall()
            return [
                {
                    **dict(r),
                    "summary": json.loads(r["summary"]),
                    "details": json.loads(r["details"]),
                }
                for r in rows
            ]

    def close(self) -> None:
        self._con.close()
