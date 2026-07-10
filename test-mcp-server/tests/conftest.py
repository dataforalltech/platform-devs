"""Fixtures compartilhadas para os testes do test-mcp-server.

O ``TestStore`` foi migrado de SQLite para PostgreSQL (psycopg2 + connection
pool). Para manter os testes **herméticos** (sem rede, sem banco real) e ainda
exercitar o SQL real do store, este conftest substitui a camada psycopg2 por um
backend SQLite in-memory equivalente:

* ``psycopg2.pool.ThreadedConnectionPool`` -> pool fake sobre uma única conexão
  SQLite in-memory (com o schema esperado pelo store criado no __init__).
* ``psycopg2.extras.RealDictCursor``       -> cursor fake que devolve linhas como
  ``dict`` e traduz os poucos dialetos PG usados (placeholders ``%s`` -> ``?`` e a
  única query com ``LEFT JOIN LATERAL``, que o SQLite não suporta).

Assim ``TestStore.__init__``, ``_get_conn``, ``close`` e todo o SQL rodam de
verdade — só o driver por baixo muda.
"""

from __future__ import annotations

import re
import sqlite3
from typing import Any

import psycopg2.extras
import psycopg2.pool
import pytest

from src.db.store import TestStore

# ── Schema equivalente ao esperado pelo store em PostgreSQL ─────────────────── #
# PKs INTEGER usam AUTOINCREMENT (equivalente a SERIAL). booleanos viram INTEGER
# (0/1); o SQLite 3.35+ aceita RETURNING, ON CONFLICT ... DO UPDATE e literais
# true/false nativamente, então nenhuma tradução extra é necessária para eles.
_SCHEMA = """
CREATE TABLE test_plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    scope TEXT NOT NULL,
    feature TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE test_scenarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    priority TEXT NOT NULL DEFAULT 'medium',
    preconditions TEXT,
    steps TEXT NOT NULL,
    expected_result TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE test_cases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id INTEGER NOT NULL,
    scenario_id INTEGER NOT NULL,
    status TEXT NOT NULL,
    actual_result TEXT,
    notes TEXT,
    evidence TEXT,
    executed_at TEXT NOT NULL
);
CREATE TABLE bug_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id INTEGER NOT NULL,
    severity TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    evidence TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL
);
CREATE TABLE quality_gates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    type TEXT NOT NULL,
    plan_id INTEGER,
    created_at TEXT NOT NULL
);
CREATE TABLE checklist_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    checklist_id TEXT NOT NULL,
    order_num INTEGER NOT NULL,
    description TEXT NOT NULL,
    required INTEGER NOT NULL DEFAULT 1,
    category TEXT
);
CREATE TABLE checklist_runs (
    id TEXT PRIMARY KEY,
    checklist_id TEXT NOT NULL,
    status TEXT NOT NULL,
    executor TEXT,
    started_at TEXT NOT NULL,
    completed_at TEXT
);
CREATE TABLE checklist_results (
    run_id TEXT NOT NULL,
    item_id INTEGER NOT NULL,
    status TEXT NOT NULL,
    notes TEXT,
    checked_at TEXT NOT NULL,
    UNIQUE (run_id, item_id)
);
"""

# A única query PG que o SQLite não entende é o LEFT JOIN LATERAL de
# get_scenarios(); reescrevemos para uma subquery escalar correlacionada
# (semanticamente idêntica: último status por cenário).
_LATERAL_RE = re.compile(
    r"SELECT\s+s\.\*,\s*tc\.status\s+as\s+last_status\s+FROM\s+test_scenarios\s+s\s+"
    r"LEFT\s+JOIN\s+LATERAL\s*\(.*?\)\s*tc\s+ON\s+true\s+"
    r"WHERE\s+s\.plan_id\s*=\s*%s\s+ORDER\s+BY\s+s\.category,\s*s\.priority",
    re.IGNORECASE | re.DOTALL,
)
_LATERAL_REWRITE = (
    "SELECT s.*, ("
    "SELECT status FROM test_cases WHERE scenario_id = s.id AND plan_id = %s "
    "ORDER BY executed_at DESC LIMIT 1"
    ") as last_status "
    "FROM test_scenarios s WHERE s.plan_id = %s "
    "ORDER BY s.category, s.priority"
)


def _translate(sql: str) -> str:
    """Traduz o SQL PostgreSQL do store para SQLite."""
    sql = _LATERAL_RE.sub(_LATERAL_REWRITE, sql)
    # placeholders posicionais: %s -> ? (o store nunca usa %(name)s)
    sql = sql.replace("%s", "?")
    return sql


class _FakeCursor:
    """Emula psycopg2 RealDictCursor sobre um cursor SQLite (linhas como dict)."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._cur = conn.cursor()

    def execute(self, sql: str, params: Any = None) -> _FakeCursor:
        self._cur.execute(_translate(sql), tuple(params) if params else ())
        return self

    def fetchone(self) -> dict[str, Any] | None:
        row = self._cur.fetchone()
        return dict(row) if row is not None else None

    def fetchall(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self._cur.fetchall()]

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *exc: object) -> None:
        self._cur.close()


class _FakeConn:
    """Emula uma conexão psycopg2 sobre uma conexão SQLite."""

    def __init__(self, sqlite_conn: sqlite3.Connection) -> None:
        self._conn = sqlite_conn

    def cursor(self, cursor_factory: Any = None) -> _FakeCursor:
        # o store sempre pede RealDictCursor; ignoramos o factory e sempre
        # devolvemos dicts (comportamento do RealDictCursor).
        return _FakeCursor(self._conn)

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()


class _FakePool:
    """Emula psycopg2 ThreadedConnectionPool sobre uma conexão SQLite in-memory."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._sqlite = sqlite3.connect(":memory:", check_same_thread=False)
        self._sqlite.row_factory = sqlite3.Row
        self._sqlite.executescript(_SCHEMA)
        self._conn = _FakeConn(self._sqlite)

    def getconn(self) -> _FakeConn:
        return self._conn

    def putconn(self, conn: _FakeConn) -> None:
        # conexão única compartilhada; nada a devolver.
        pass

    def closeall(self) -> None:
        self._sqlite.close()


@pytest.fixture
def store(monkeypatch) -> TestStore:
    """TestStore real com a camada psycopg2 trocada por SQLite in-memory."""
    # RealDictCursor é referenciado no store; o _FakeConn.cursor o ignora, mas
    # deixamos o símbolo intacto (não precisa patch). Só o pool precisa ser fake.
    monkeypatch.setattr(psycopg2.pool, "ThreadedConnectionPool", _FakePool)
    from src.config.settings import TestSettings

    return TestStore(settings=TestSettings())


@pytest.fixture
def plan(store: TestStore) -> dict:
    """Plano de teste pré-criado."""
    return store.create_plan(title="Plano de Teste", scope="Endpoint GET /api/items", feature="items-list")
