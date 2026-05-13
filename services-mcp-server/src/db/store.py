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


class ServiceStore:
    def __init__(self, db_path: str = ":memory:") -> None:
        self._pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=2,
            maxconn=10,
            dsn=os.getenv("PG_DSN", "postgresql://localhost/services_mcp"),
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
                    ALTER TABLE services ADD COLUMN IF NOT EXISTS internal_url TEXT;
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS services (
                        name           TEXT PRIMARY KEY,
                        host           TEXT NOT NULL DEFAULT 'localhost',
                        port           INTEGER,
                        url            TEXT,
                        internal_url   TEXT,
                        type           TEXT NOT NULL DEFAULT 'unknown',
                        container_name TEXT,
                        pid            INTEGER,
                        status         TEXT NOT NULL DEFAULT 'unknown',
                        health_path    TEXT DEFAULT '/health',
                        environment    TEXT NOT NULL DEFAULT 'local',
                        tags           TEXT NOT NULL DEFAULT '[]',
                        metadata       TEXT NOT NULL DEFAULT '{}',
                        registered_at  TEXT,
                        last_seen      TEXT,
                        last_check_at  TEXT,
                        last_check_ok  INTEGER
                    );
                """)

    def upsert(self, name: str, fields: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            with self._get_conn() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute(
                        "SELECT name FROM services WHERE name=%s", (name,)
                    )
                    existing = cur.fetchone()
                    if existing is None:
                        fields.setdefault("registered_at", _now())
                        fields["name"] = name
                        if "tags" in fields and isinstance(fields["tags"], list):
                            fields["tags"] = json.dumps(fields["tags"])
                        if "metadata" in fields and isinstance(fields["metadata"], dict):
                            fields["metadata"] = json.dumps(fields["metadata"])
                        cols = ", ".join(fields.keys())
                        placeholders = ", ".join(["%s"] * len(fields))
                        cur.execute(
                            f"INSERT INTO services ({cols}) VALUES ({placeholders})",
                            list(fields.values()),
                        )
                        action = "created"
                    else:
                        if "tags" in fields and isinstance(fields["tags"], list):
                            fields["tags"] = json.dumps(fields["tags"])
                        if "metadata" in fields and isinstance(fields["metadata"], dict):
                            fields["metadata"] = json.dumps(fields["metadata"])
                        fields["last_seen"] = _now()
                        sets = ", ".join(f"{k}=%s" for k in fields)
                        cur.execute(
                            f"UPDATE services SET {sets} WHERE name=%s",
                            [*fields.values(), name],
                        )
                        action = "updated"

                    cur.execute("SELECT * FROM services WHERE name=%s", (name,))
                    row = cur.fetchone()
                    return {"action": action, "row": dict(row)}

    def get(self, name: str) -> dict | None:
        with self._lock:
            with self._get_conn() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute("SELECT * FROM services WHERE name=%s", (name,))
                    row = cur.fetchone()
                    return dict(row) if row else None

    def list_all(
        self,
        environment: str | None = None,
        type_: str | None = None,
        status: str | None = None,
        tag: str | None = None,
    ) -> list[dict]:
        with self._lock:
            with self._get_conn() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    query = "SELECT * FROM services WHERE 1=1"
                    params: list[Any] = []
                    if environment:
                        query += " AND environment=%s"
                        params.append(environment)
                    if type_:
                        query += " AND type=%s"
                        params.append(type_)
                    if status:
                        query += " AND status=%s"
                        params.append(status)
                    query += " ORDER BY name"
                    cur.execute(query, params)
                    rows = cur.fetchall()
                    result = [dict(r) for r in rows]
                    if tag:
                        result = [r for r in result if tag in json.loads(r.get("tags") or "[]")]
                    return result

    def delete(self, name: str) -> bool:
        with self._lock:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM services WHERE name=%s", (name,))
                    deleted = cur.rowcount > 0

            return deleted

    def update_check(self, name: str, ok: bool) -> None:
        with self._lock:
            now = _now()
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE services SET last_check_at=%s, last_check_ok=%s WHERE name=%s",
                        (now, 1 if ok else 0, name),
                    )

    def close(self) -> None:
        if self._pool:
            self._pool.closeall()
        _log.info("âœ… ServiceStore closed: PostgreSQL pool")
