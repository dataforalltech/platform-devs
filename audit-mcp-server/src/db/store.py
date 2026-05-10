import json
import sqlite3
import threading
import uuid
import os
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)


class AuditStore:
    """SQLite store for audit data. Thread-safe with WAL mode."""

    def __init__(self, db_path: str = ".audit.db"):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        if db_path != ":memory:":
            self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.row_factory = sqlite3.Row
        self._init_db()

        # Initialize PostgreSQL sync layer
        self._postgres_sync = None
        if os.getenv("POSTGRES_SYNC_ENABLED", "false").lower() == "true":
            try:
                from db.postgres_sync import AuditPostgresSync
                postgres_config = {
                    "host": os.getenv("POSTGRES_HOST", "claude-dev"),
                    "port": int(os.getenv("POSTGRES_PORT", "5432")),
                    "user": os.getenv("POSTGRES_USER", "postgres"),
                    "password": os.getenv("POSTGRES_PASSWORD", "postgres_password_local_dev"),
                    "database": os.getenv("POSTGRES_DB", "app"),
                }
                self._postgres_sync = AuditPostgresSync(postgres_config, enabled=True)
                _log.info("✅ AuditStore: PostgreSQL sync enabled")
            except Exception as e:
                _log.warning(f"⚠️  AuditStore: PostgreSQL sync disabled: {e}")

    def _init_db(self) -> None:
        with self._lock:
            cursor = self._conn.cursor()

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS audits (
                    id TEXT PRIMARY KEY,
                    service TEXT NOT NULL,
                    repo TEXT NOT NULL,
                    env TEXT NOT NULL,
                    criticality TEXT NOT NULL,
                    score REAL NOT NULL,
                    passed INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    checklist TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS audit_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    audit_id TEXT NOT NULL,
                    category TEXT NOT NULL,
                    name TEXT NOT NULL,
                    required INTEGER NOT NULL,
                    passed INTEGER NOT NULL,
                    details TEXT,
                    FOREIGN KEY(audit_id) REFERENCES audits(id)
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS audit_approvals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    audit_id TEXT NOT NULL,
                    approved_by TEXT NOT NULL,
                    role TEXT,
                    decision TEXT NOT NULL,
                    notes TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(audit_id) REFERENCES audits(id)
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS service_config (
                    service TEXT PRIMARY KEY,
                    criticality TEXT NOT NULL DEFAULT 'medium',
                    updated_by TEXT,
                    updated_at TEXT NOT NULL
                )
            """)

            self._conn.commit()

    def create_audit(
        self,
        service: str,
        repo: str,
        env: str,
        criticality: str,
        score: float,
        passed: bool,
        status: str,
        checklist: dict[str, Any],
    ) -> str:
        audit_id = f"audit_{uuid.uuid4().hex[:12]}"
        now = datetime.utcnow().isoformat()

        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(
                """
                INSERT INTO audits
                (id, service, repo, env, criticality, score, passed, status, checklist, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    audit_id,
                    service,
                    repo,
                    env,
                    criticality,
                    score,
                    1 if passed else 0,
                    status,
                    json.dumps(checklist),
                    now,
                    now,
                ),
            )
            self._conn.commit()

        # Sync to PostgreSQL
        if self._postgres_sync:
            try:
                audit_data = {
                    'id': audit_id,
                    'service': service,
                    'repo': repo,
                    'env': env,
                    'criticality': criticality,
                    'score': score,
                    'passed': passed,
                    'status': status,
                    'checklist': checklist,
                }
                self._postgres_sync.sync_audit_created(audit_data)
            except Exception as e:
                _log.warning(f"Failed to sync audit created to PostgreSQL: {e}")

        return audit_id

    def get_audit(self, audit_id: str) -> dict[str, Any] | None:
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute("SELECT * FROM audits WHERE id = ?", (audit_id,))
            row = cursor.fetchone()

            if not row:
                return None

            return self._row_to_dict(row)

    def get_latest_audit(self, service: str, env: str) -> dict[str, Any] | None:
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(
                """
                SELECT * FROM audits
                WHERE service = ? AND env = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (service, env),
            )
            row = cursor.fetchone()

            if not row:
                return None

            return self._row_to_dict(row)

    def list_audits(
        self,
        status: str | None = None,
        env: str | None = None,
        service: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        with self._lock:
            cursor = self._conn.cursor()

            query = "SELECT * FROM audits WHERE 1=1"
            params: list[Any] = []

            if status:
                query += " AND status = ?"
                params.append(status)
            if env:
                query += " AND env = ?"
                params.append(env)
            if service:
                query += " AND service = ?"
                params.append(service)

            query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])

            cursor.execute(query, params)
            rows = cursor.fetchall()

            return [self._row_to_dict(row) for row in rows]

    def update_audit_status(self, audit_id: str, status: str, score: float, passed: bool) -> None:
        now = datetime.utcnow().isoformat()

        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(
                """
                UPDATE audits
                SET status = ?, score = ?, passed = ?, updated_at = ?
                WHERE id = ?
                """,
                (status, score, 1 if passed else 0, now, audit_id),
            )
            self._conn.commit()

        # Sync to PostgreSQL
        if self._postgres_sync:
            try:
                updates = {
                    'status': status,
                    'score': score,
                    'passed': passed,
                }
                self._postgres_sync.sync_audit_updated(audit_id, updates)
            except Exception as e:
                _log.warning(f"Failed to sync audit updated to PostgreSQL: {e}")

    def add_audit_item(
        self,
        audit_id: str,
        category: str,
        name: str,
        required: bool,
        passed: bool,
        details: str | None = None,
    ) -> None:
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(
                """
                INSERT INTO audit_items (audit_id, category, name, required, passed, details)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (audit_id, category, name, 1 if required else 0, 1 if passed else 0, details),
            )
            self._conn.commit()

        # Sync to PostgreSQL
        if self._postgres_sync:
            try:
                item_data = {
                    'category': category,
                    'name': name,
                    'required': required,
                    'passed': passed,
                    'details': details,
                }
                self._postgres_sync.sync_audit_item_added(audit_id, item_data)
            except Exception as e:
                _log.warning(f"Failed to sync audit item to PostgreSQL: {e}")

    def get_audit_items(self, audit_id: str) -> list[dict[str, Any]]:
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute("SELECT * FROM audit_items WHERE audit_id = ?", (audit_id,))
            rows = cursor.fetchall()

            return [self._row_to_dict(row) for row in rows]

    def add_approval(
        self,
        audit_id: str,
        approved_by: str,
        decision: str,
        role: str | None = None,
        notes: str | None = None,
    ) -> None:
        now = datetime.utcnow().isoformat()

        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(
                """
                INSERT INTO audit_approvals (audit_id, approved_by, role, decision, notes, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (audit_id, approved_by, role, decision, notes, now),
            )
            self._conn.commit()

        # Sync to PostgreSQL
        if self._postgres_sync:
            try:
                approval_data = {
                    'approved_by': approved_by,
                    'decision': decision,
                    'role': role,
                    'notes': notes,
                }
                self._postgres_sync.sync_approval_added(audit_id, approval_data)
            except Exception as e:
                _log.warning(f"Failed to sync approval to PostgreSQL: {e}")

    def get_approvals(self, audit_id: str) -> list[dict[str, Any]]:
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(
                """
                SELECT * FROM audit_approvals WHERE audit_id = ?
                ORDER BY created_at DESC
                """,
                (audit_id,),
            )
            rows = cursor.fetchall()

            return [self._row_to_dict(row) for row in rows]

    def set_service_criticality(self, service: str, criticality: str, updated_by: str) -> None:
        now = datetime.utcnow().isoformat()

        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(
                """
                INSERT OR REPLACE INTO service_config (service, criticality, updated_by, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (service, criticality, updated_by, now),
            )
            self._conn.commit()

        # Sync to PostgreSQL
        if self._postgres_sync:
            try:
                self._postgres_sync.sync_service_criticality(service, criticality, updated_by)
            except Exception as e:
                _log.warning(f"Failed to sync service criticality to PostgreSQL: {e}")

    def get_service_criticality(self, service: str) -> str:
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(
                "SELECT criticality FROM service_config WHERE service = ?", (service,)
            )
            row = cursor.fetchone()

            return row["criticality"] if row else "medium"

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        if "passed" in d:
            d["passed"] = bool(d["passed"])
        if "required" in d:
            d["required"] = bool(d["required"])
        if "checklist" in d and isinstance(d["checklist"], str):
            d["checklist"] = json.loads(d["checklist"])
        return d
