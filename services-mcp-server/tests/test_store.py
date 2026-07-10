"""Testes do ``ServiceStore`` real (src/db/store.py) com psycopg2 mockado.

O store abre um pool psycopg2 contra um PostgreSQL no ``__init__``; aqui esse pool
é substituído por um fake in-memory que entende exatamente o SQL emitido pelo
store (CREATE/ALTER no-op, SELECT/INSERT/UPDATE/DELETE sobre uma tabela dict).
Assim o código Python do store é exercido sem I/O de banco (FID-01).
"""

from __future__ import annotations

import re
from typing import Any

import pytest

import src.db.store as store_mod
from src.db.store import ServiceStore


class _FakeCursor:
    def __init__(self, table: dict[str, dict[str, Any]]):
        self._table = table
        self._result: Any = None
        self._results: list[dict] = []
        self.rowcount = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql: str, params: Any = None):  # noqa: C901
        s = " ".join(sql.split())
        params = list(params) if params else []
        if s.startswith("CREATE TABLE") or s.startswith("ALTER TABLE"):
            return
        if s.startswith("SELECT name FROM services WHERE name="):
            self._result = self._table.get(params[0])
            return
        if s.startswith("SELECT * FROM services WHERE name="):
            self._result = self._table.get(params[0])
            return
        if s.startswith("INSERT INTO services"):
            cols = s[s.index("(") + 1 : s.index(")")].split(", ")
            row = dict(zip(cols, params, strict=False))
            self._table[row["name"]] = row
            return
        if s.startswith("UPDATE services SET"):
            sets = s[len("UPDATE services SET ") : s.index(" WHERE name=")]
            keys = [c.split("=")[0].strip() for c in sets.split(",")]
            name = params[-1]
            values = params[:-1]
            row = self._table.get(name)
            if row is not None:
                row.update(dict(zip(keys, values, strict=False)))
            return
        if s.startswith("DELETE FROM services WHERE name="):
            name = params[0]
            self.rowcount = 1 if self._table.pop(name, None) is not None else 0
            return
        if s.startswith("SELECT * FROM services WHERE 1=1"):
            conds = re.findall(r"AND (\w+)=%s", s)
            rows = list(self._table.values())
            for col, val in zip(conds, params, strict=False):
                rows = [r for r in rows if r.get(col) == val]
            rows.sort(key=lambda r: r.get("name", ""))
            self._results = rows
            return
        raise AssertionError(f"SQL não previsto pelo fake: {s}")

    def fetchone(self):
        return self._result

    def fetchall(self):
        return self._results


class _FakeConn:
    def __init__(self, table):
        self._table = table

    def cursor(self, cursor_factory=None):
        return _FakeCursor(self._table)

    def commit(self):
        pass

    def rollback(self):
        pass


class _FakePool:
    def __init__(self, *a, **k):
        self._table: dict[str, dict[str, Any]] = {}
        self.closed = False

    def getconn(self):
        return _FakeConn(self._table)

    def putconn(self, conn):
        pass

    def closeall(self):
        self.closed = True


@pytest.fixture()
def store(monkeypatch):
    monkeypatch.setattr(store_mod.psycopg2.pool, "ThreadedConnectionPool", _FakePool)
    s = ServiceStore()
    yield s
    s.close()


def test_upsert_create_then_get(store):
    res = store.upsert("api", {"port": 8080, "type": "docker", "tags": ["a"], "metadata": {"k": 1}})
    assert res["action"] == "created"
    assert res["row"]["name"] == "api"
    # tags/metadata serializados como JSON string
    assert res["row"]["tags"] == '["a"]'
    got = store.get("api")
    assert got["port"] == 8080


def test_upsert_update_existing(store):
    store.upsert("api", {"port": 8080})
    res = store.upsert("api", {"status": "running", "tags": ["x"]})
    assert res["action"] == "updated"
    assert res["row"]["status"] == "running"


def test_get_missing_returns_none(store):
    assert store.get("ghost") is None


def test_list_all_and_filters(store):
    store.upsert("a", {"environment": "dev", "type": "docker", "tags": ["t1"]})
    store.upsert("b", {"environment": "prod", "type": "process", "tags": ["t2"]})
    assert len(store.list_all()) == 2
    assert [r["name"] for r in store.list_all(environment="dev")] == ["a"]
    assert [r["name"] for r in store.list_all(type_="process")] == ["b"]
    # filtro por tag é aplicado em Python sobre o JSON serializado
    assert [r["name"] for r in store.list_all(tag="t1")] == ["a"]
    assert store.list_all(tag="nope") == []


def test_delete(store):
    store.upsert("a", {"port": 1})
    assert store.delete("a") is True
    assert store.delete("a") is False


def test_update_check(store):
    store.upsert("a", {"port": 1})
    store.update_check("a", ok=True)
    assert store.get("a")["last_check_ok"] == 1
    store.update_check("a", ok=False)
    assert store.get("a")["last_check_ok"] == 0


def test_close_marks_pool_closed(store):
    store.close()
    assert store._pool.closed is True
