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


class ServiceStore:
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
                from db.postgres_sync import ServicesPostgresSync
                postgres_config = {
                    "host": os.getenv("POSTGRES_HOST", "claude-dev"),
                    "port": int(os.getenv("POSTGRES_PORT", "5432")),
                    "user": os.getenv("POSTGRES_USER", "postgres"),
                    "password": os.getenv("POSTGRES_PASSWORD", "postgres_password_local_dev"),
                    "database": os.getenv("POSTGRES_DB", "app"),
                }
                self._postgres_sync = ServicesPostgresSync(postgres_config, enabled=True)
                _log.info("✅ ServiceStore: PostgreSQL sync enabled")
            except Exception as e:
                _log.warning(f"⚠️  ServiceStore: PostgreSQL sync disabled: {e}")

    def _migrate(self) -> None:
        self._con.executescript("""
            CREATE TABLE IF NOT EXISTS services (
                name           TEXT PRIMARY KEY,
                host           TEXT NOT NULL DEFAULT 'localhost',
                port           INTEGER,
                url            TEXT,
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
            existing = self._con.execute(
                "SELECT name FROM services WHERE name=?", (name,)
            ).fetchone()
            if existing is None:
                fields.setdefault("registered_at", _now())
                fields["name"] = name
                if "tags" in fields and isinstance(fields["tags"], list):
                    fields["tags"] = json.dumps(fields["tags"])
                if "metadata" in fields and isinstance(fields["metadata"], dict):
                    fields["metadata"] = json.dumps(fields["metadata"])
                cols = ", ".join(fields.keys())
                placeholders = ", ".join("?" * len(fields))
                self._con.execute(
                    f"INSERT INTO services ({cols}) VALUES ({placeholders})",
                    list(fields.values()),
                )
                action = "created"

                # Sync to PostgreSQL
                if self._postgres_sync:
                    try:
                        service_data = dict(fields)
                        service_data["name"] = name
                        self._postgres_sync.sync_service_registered(service_data)
                    except Exception as e:
                        _log.warning(f"Failed to sync service registered to PostgreSQL: {e}")
            else:
                if "tags" in fields and isinstance(fields["tags"], list):
                    fields["tags"] = json.dumps(fields["tags"])
                if "metadata" in fields and isinstance(fields["metadata"], dict):
                    fields["metadata"] = json.dumps(fields["metadata"])
                fields["last_seen"] = _now()
                sets = ", ".join(f"{k}=?" for k in fields)
                self._con.execute(
                    f"UPDATE services SET {sets} WHERE name=?",
                    [*fields.values(), name],
                )
                action = "updated"

                # Sync to PostgreSQL
                if self._postgres_sync:
                    try:
                        self._postgres_sync.sync_service_updated(name, fields)
                    except Exception as e:
                        _log.warning(f"Failed to sync service updated to PostgreSQL: {e}")

            row = self._con.execute("SELECT * FROM services WHERE name=?", (name,)).fetchone()
            return {"action": action, "row": dict(row)}

    def get(self, name: str) -> dict | None:
        with self._lock:
            row = self._con.execute("SELECT * FROM services WHERE name=?", (name,)).fetchone()
            return dict(row) if row else None

    def list_all(
        self,
        environment: str | None = None,
        type_: str | None = None,
        status: str | None = None,
        tag: str | None = None,
    ) -> list[dict]:
        with self._lock:
            query = "SELECT * FROM services WHERE 1=1"
            params: list[Any] = []
            if environment:
                query += " AND environment=?"
                params.append(environment)
            if type_:
                query += " AND type=?"
                params.append(type_)
            if status:
                query += " AND status=?"
                params.append(status)
            query += " ORDER BY name"
            rows = self._con.execute(query, params).fetchall()
            result = [dict(r) for r in rows]
            if tag:
                result = [r for r in result if tag in json.loads(r.get("tags") or "[]")]
            return result

    def delete(self, name: str) -> bool:
        with self._lock:
            cur = self._con.execute("DELETE FROM services WHERE name=?", (name,))
            deleted = cur.rowcount > 0

            # Sync to PostgreSQL
            if deleted and self._postgres_sync:
                try:
                    self._postgres_sync.sync_service_removed(name)
                except Exception as e:
                    _log.warning(f"Failed to sync service removal to PostgreSQL: {e}")

            return deleted

    def update_check(self, name: str, ok: bool) -> None:
        with self._lock:
            now = _now()
            self._con.execute(
                "UPDATE services SET last_check_at=?, last_check_ok=? WHERE name=?",
                (now, 1 if ok else 0, name),
            )

            # Sync to PostgreSQL
            if self._postgres_sync:
                try:
                    status = "healthy" if ok else "unhealthy"
                    self._postgres_sync.sync_health_check_result(name, status)
                except Exception as e:
                    _log.warning(f"Failed to sync health check to PostgreSQL: {e}")

    def close(self) -> None:
        self._con.close()
