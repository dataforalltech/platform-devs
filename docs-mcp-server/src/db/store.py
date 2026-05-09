from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class DocsStore:
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
            CREATE TABLE IF NOT EXISTS audits (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                repo_path   TEXT NOT NULL,
                started_at  TEXT NOT NULL,
                duration_ms INTEGER,
                score       INTEGER NOT NULL,
                grade       TEXT NOT NULL,
                summary     TEXT NOT NULL DEFAULT '{}',
                details     TEXT NOT NULL DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS idx_audits_repo ON audits(repo_path, started_at DESC);

            CREATE TABLE IF NOT EXISTS doc_index (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                repo_path     TEXT NOT NULL,
                file_path     TEXT NOT NULL,
                doc_type      TEXT,
                title         TEXT,
                word_count    INTEGER DEFAULT 0,
                last_modified TEXT,
                content_hash  TEXT,
                UNIQUE(repo_path, file_path)
            );
            CREATE INDEX IF NOT EXISTS idx_doc_index_repo ON doc_index(repo_path);
        """)

    def save_audit(
        self,
        repo_path: str,
        score: int,
        grade: str,
        summary: dict,
        details: dict,
        duration_ms: int | None = None,
    ) -> int:
        with self._lock:
            cur = self._con.execute(
                """INSERT INTO audits
                   (repo_path, started_at, duration_ms, score, grade, summary, details)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    repo_path,
                    _now(),
                    duration_ms,
                    score,
                    grade,
                    json.dumps(summary),
                    json.dumps(details),
                ),
            )
            return cur.lastrowid  # type: ignore[return-value]

    def list_audits(
        self,
        repo_path: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        with self._lock:
            q = "SELECT * FROM audits WHERE 1=1"
            params: list[Any] = []
            if repo_path:
                q += " AND repo_path=?"
                params.append(repo_path)
            q += " ORDER BY id DESC LIMIT ?"
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

    def upsert_doc_index(
        self,
        repo_path: str,
        file_path: str,
        doc_type: str | None,
        title: str | None,
        word_count: int,
        last_modified: str | None,
        content_hash: str | None,
    ) -> None:
        with self._lock:
            self._con.execute(
                """INSERT INTO doc_index
                   (repo_path, file_path, doc_type, title, word_count, last_modified, content_hash)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(repo_path, file_path) DO UPDATE SET
                       doc_type=excluded.doc_type,
                       title=excluded.title,
                       word_count=excluded.word_count,
                       last_modified=excluded.last_modified,
                       content_hash=excluded.content_hash""",
                (repo_path, file_path, doc_type, title, word_count, last_modified, content_hash),
            )

    def search_index(self, repo_path: str, query: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._con.execute(
                "SELECT * FROM doc_index WHERE repo_path=? AND title LIKE ? ORDER BY title",
                (repo_path, f"%{query}%"),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_index(self, repo_path: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._con.execute(
                "SELECT * FROM doc_index WHERE repo_path=? ORDER BY file_path",
                (repo_path,),
            ).fetchall()
            return [dict(r) for r in rows]

    def close(self) -> None:
        self._con.close()
