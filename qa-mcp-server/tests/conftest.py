from __future__ import annotations

import re
import sqlite3
import threading

import psycopg2.pool
import pytest

from src.config.settings import QASettings
from src.db.store import QAStore

# --------------------------------------------------------------------------- #
# Hermetic PostgreSQL fake.                                                    #
#                                                                             #
# QAStore (src/db/store.py) talks to PostgreSQL via a psycopg2 connection      #
# pool. CI has no Postgres server, so a real connection blocks/refuses. We     #
# replace psycopg2.pool.ThreadedConnectionPool with an in-process SQLite-backed #
# fake that mimics the psycopg2 API surface QAStore actually uses:             #
#   pool.getconn / putconn / closeall                                          #
#   conn.commit / rollback / cursor(cursor_factory=...)                        #
#   cursor as context manager, execute() with %s params, fetchone/fetchall,    #
#   RETURNING id, and RealDictCursor (dict-like rows).                         #
# Production code is untouched; only the transport is faked in tests.          #
# --------------------------------------------------------------------------- #


def _pg_sql_to_sqlite(sql: str) -> str:
    """Translate the (small, fixed) set of PG statements QAStore issues to SQLite."""
    sql = sql.replace("%s", "?")
    sql = sql.replace("SERIAL PRIMARY KEY", "INTEGER PRIMARY KEY AUTOINCREMENT")
    return sql


class _FakeCursor:
    def __init__(self, sqlite_conn: sqlite3.Connection, *, as_dict: bool) -> None:
        self._conn = sqlite_conn
        self._as_dict = as_dict
        self._cur: sqlite3.Cursor | None = None
        self._returning = False

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *exc) -> bool:
        if self._cur is not None:
            self._cur.close()
        return False

    def execute(self, sql: str, params: tuple | list | None = None) -> None:
        translated = _pg_sql_to_sqlite(sql)
        # SQLite has no RETURNING on older versions; emulate via lastrowid.
        self._returning = bool(re.search(r"returning\s+id", translated, re.IGNORECASE))
        if self._returning:
            translated = re.sub(r"returning\s+id", "", translated, flags=re.IGNORECASE).strip()
        self._cur = self._conn.execute(translated, tuple(params) if params else ())

    def fetchone(self):
        assert self._cur is not None
        if self._returning:
            return (self._cur.lastrowid,)
        return self._cur.fetchone()

    def fetchall(self):
        assert self._cur is not None
        rows = self._cur.fetchall()
        if self._as_dict:
            return [dict(r) for r in rows]
        return rows


class _FakeConnection:
    def __init__(self, sqlite_conn: sqlite3.Connection) -> None:
        self._conn = sqlite_conn

    def cursor(self, cursor_factory=None):
        # RealDictCursor -> dict rows. Detect by name to avoid importing internals.
        as_dict = cursor_factory is not None and "RealDict" in getattr(cursor_factory, "__name__", "")
        return _FakeCursor(self._conn, as_dict=as_dict)

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()


class _FakePool:
    """Single shared in-memory SQLite DB behind a psycopg2-pool-shaped facade."""

    def __init__(self, *args, **kwargs) -> None:
        self._sqlite = sqlite3.connect(":memory:", check_same_thread=False)
        self._sqlite.row_factory = sqlite3.Row
        self._lock = threading.Lock()

    def getconn(self):
        # QAStore serializes access with its own lock; hand out one wrapper.
        self._lock.acquire()
        return _FakeConnection(self._sqlite)

    def putconn(self, conn) -> None:
        if self._lock.locked():
            self._lock.release()

    def closeall(self) -> None:
        self._sqlite.close()


@pytest.fixture(autouse=True)
def _fake_pg_pool(monkeypatch):
    """Replace the PG connection pool with the SQLite-backed fake for every test."""
    monkeypatch.setattr(psycopg2.pool, "ThreadedConnectionPool", _FakePool)
    yield


@pytest.fixture
def store():
    s = QAStore(db_path=":memory:")
    yield s
    s.close()


@pytest.fixture
def settings():
    return QASettings(
        db_path=":memory:",
        screenshots_dir="/tmp/qa-test-screenshots",
        baselines_dir="/tmp/qa-test-baselines",
        http_timeout=5.0,
        subprocess_timeout=30,
    )
