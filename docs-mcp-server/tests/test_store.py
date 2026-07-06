"""Hermetic tests for the PostgreSQL-backed DocsStore.

psycopg2 is fully mocked (no real database, no network). A tiny in-memory
``FakeCursor`` reproduces just enough of the psycopg2 cursor contract that the
store exercises: ``execute``, ``fetchone``, ``fetchall``, ``rowcount`` and the
context-manager protocol. This lets us cover the store's SQL-building/branching
logic (INSERT ... RETURNING, update-then-insert upsert, RealDictCursor reads,
pool commit/rollback) without a live Postgres.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import src.db.store as store_mod
from src.config.settings import DocsSettings
from src.db.store import DocsStore, _now


class FakeCursor:
    def __init__(self, *, dict_rows: list[dict] | None = None, returning_id: int | None = None):
        self._dict_rows = dict_rows or []
        self._returning_id = returning_id
        self.rowcount = 0
        self.executed: list[tuple] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, query, params=None):
        self.executed.append((query, params))
        # Simulate an UPDATE that matched nothing so upsert falls through to INSERT.
        if query.strip().upper().startswith("UPDATE"):
            self.rowcount = 0
        else:
            self.rowcount = 1

    def fetchone(self):
        return (self._returning_id,) if self._returning_id is not None else None

    def fetchall(self):
        return self._dict_rows


class FakeConn:
    def __init__(self, cursor: FakeCursor):
        self._cursor = cursor
        self.committed = False
        self.rolled_back = False

    def cursor(self, cursor_factory=None):
        return self._cursor

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


class FakePool:
    def __init__(self, conn: FakeConn):
        self._conn = conn
        self.returned = []
        self.closed = False

    def getconn(self):
        return self._conn

    def putconn(self, conn):
        self.returned.append(conn)

    def closeall(self):
        self.closed = True


def _make_store(monkeypatch, cursor: FakeCursor) -> tuple[DocsStore, FakeConn, FakePool]:
    conn = FakeConn(cursor)
    pool = FakePool(conn)
    monkeypatch.setattr(
        store_mod.psycopg2.pool,
        "ThreadedConnectionPool",
        lambda *a, **k: pool,
    )
    settings = DocsSettings()
    st = DocsStore(settings=settings)
    return st, conn, pool


def test_now_is_iso_with_timezone():
    value = _now()
    assert value.endswith("+00:00")


def test_save_audit_returns_inserted_id(monkeypatch):
    cur = FakeCursor(returning_id=42)
    st, conn, pool = _make_store(monkeypatch, cur)

    audit_id = st.save_audit(
        repo_path="/repo",
        score=88,
        grade="B",
        summary={"total_docs": 3},
        details={"x": 1},
        duration_ms=12,
    )

    assert audit_id == 42
    assert conn.committed is True
    # connection returned to the pool
    assert pool.returned == [conn]


def test_get_conn_rolls_back_on_error(monkeypatch):
    cur = FakeCursor()

    def boom(query, params=None):
        raise RuntimeError("db exploded")

    cur.execute = boom  # type: ignore[method-assign]
    st, conn, pool = _make_store(monkeypatch, cur)

    with pytest.raises(RuntimeError, match="db exploded"):
        st.save_audit(
            repo_path="/repo",
            score=1,
            grade="F",
            summary={},
            details={},
        )

    assert conn.rolled_back is True
    assert conn.committed is False
    assert pool.returned == [conn]  # still returned in finally


def test_list_audits_maps_rows_and_filters_by_repo(monkeypatch):
    rows = [
        {
            "id": 2,
            "repo_path": "/repo",
            "title": "Audit: B",
            "content": '{"score": 80, "grade": "B", "summary": {"a": 1}, "details": {"d": 2}}',
            "created_at": "2026-01-02T00:00:00+00:00",
        }
    ]
    cur = FakeCursor(dict_rows=rows)
    st, conn, _pool = _make_store(monkeypatch, cur)

    result = st.list_audits(repo_path="/repo", limit=5)

    assert len(result) == 1
    assert result[0]["id"] == 2
    assert result[0]["score"] == 80
    assert result[0]["grade"] == "B"
    assert result[0]["summary"] == {"a": 1}
    assert result[0]["details"] == {"d": 2}
    # repo_path filter appended to params
    _query, params = cur.executed[-1]
    assert "/repo" in params


def test_list_audits_without_repo_filter(monkeypatch):
    cur = FakeCursor(dict_rows=[])
    st, _conn, _pool = _make_store(monkeypatch, cur)

    result = st.list_audits(limit=3)

    assert result == []
    _query, params = cur.executed[-1]
    # only the doc_type marker and limit — no repo_path
    assert params == ["audit", 3]


def test_upsert_inserts_when_update_matches_nothing(monkeypatch):
    cur = FakeCursor()  # UPDATE returns rowcount 0 → triggers INSERT
    st, conn, _pool = _make_store(monkeypatch, cur)

    st.upsert_doc_index(
        repo_path="/repo",
        file_path="README.md",
        doc_type="readme",
        title="My Service",
        word_count=120,
        last_modified="2026-01-01T00:00:00+00:00",
        content_hash="abc123",
    )

    # both UPDATE and INSERT statements ran
    statements = [q.strip().upper()[:6] for q, _ in cur.executed]
    assert "UPDATE" in statements
    assert "INSERT" in statements
    # the JSON payload carries the real doc title
    _insert_q, insert_params = cur.executed[-1]
    assert any("My Service" in str(p) for p in insert_params)
    assert conn.committed is True


def test_upsert_updates_when_row_exists(monkeypatch):
    cur = FakeCursor()
    cur.rowcount = 1  # ignored; execute() sets rowcount per-statement

    # Force UPDATE to "match" a row so INSERT is skipped.
    real_execute = cur.execute

    def execute(query, params=None):
        real_execute(query, params)
        if query.strip().upper().startswith("UPDATE"):
            cur.rowcount = 1

    cur.execute = execute  # type: ignore[method-assign]
    st, _conn, _pool = _make_store(monkeypatch, cur)

    st.upsert_doc_index(
        repo_path="/repo",
        file_path="README.md",
        doc_type="readme",
        title="My Service",
        word_count=10,
        last_modified=None,
        content_hash=None,
    )

    statements = [q.strip().upper()[:6] for q, _ in cur.executed]
    assert statements == ["UPDATE"]  # no INSERT because UPDATE matched


def test_search_index_maps_content(monkeypatch):
    rows = [
        {
            "id": 5,
            "repo_path": "/repo",
            "doc_type": "readme",
            "title": "README.md",
            "content": '{"word_count": 42, "last_modified": "t", "content_hash": "h", '
            '"file_path": "README.md", "doc_title": "My Service"}',
            "created_at": "2026-01-01T00:00:00+00:00",
        }
    ]
    cur = FakeCursor(dict_rows=rows)
    st, _conn, _pool = _make_store(monkeypatch, cur)

    result = st.search_index("/repo", "Serv")

    assert result[0]["title"] == "My Service"
    assert result[0]["word_count"] == 42
    assert result[0]["file_path"] == "README.md"


def test_get_index_maps_content(monkeypatch):
    rows = [
        {
            "id": 7,
            "repo_path": "/repo",
            "doc_type": "readme",
            "title": "README.md",
            "content": '{"word_count": 9, "last_modified": null, "content_hash": null, '
            '"file_path": "README.md", "doc_title": "Docs Home"}',
            "created_at": "2026-01-01T00:00:00+00:00",
        }
    ]
    cur = FakeCursor(dict_rows=rows)
    st, _conn, _pool = _make_store(monkeypatch, cur)

    result = st.get_index("/repo")

    assert result[0]["title"] == "Docs Home"
    assert result[0]["word_count"] == 9


def test_get_index_handles_empty_content(monkeypatch):
    rows = [
        {
            "id": 8,
            "repo_path": "/repo",
            "doc_type": None,
            "title": "notes.md",
            "content": None,
            "created_at": "2026-01-01T00:00:00+00:00",
        }
    ]
    cur = FakeCursor(dict_rows=rows)
    st, _conn, _pool = _make_store(monkeypatch, cur)

    result = st.get_index("/repo")

    # falls back to the title column when content json is missing
    assert result[0]["title"] == "notes.md"
    assert result[0]["word_count"] == 0


def test_close_closes_pool(monkeypatch):
    cur = FakeCursor()
    st, _conn, pool = _make_store(monkeypatch, cur)

    st.close()

    assert pool.closed is True


def test_init_logs_and_builds_pool(monkeypatch):
    """The pool is built from settings; dsn/min/max forwarded."""
    captured = {}

    def fake_pool(minconn, maxconn, dsn):
        captured["minconn"] = minconn
        captured["maxconn"] = maxconn
        captured["dsn"] = dsn
        return MagicMock()

    monkeypatch.setattr(store_mod.psycopg2.pool, "ThreadedConnectionPool", fake_pool)
    settings = DocsSettings(pg_min_conn=3, pg_max_conn=9)
    DocsStore(settings=settings)

    assert captured["minconn"] == 3
    assert captured["maxconn"] == 9
    assert "dbname=" in captured["dsn"]
