"""Testes do TokenStore alternativo (src/knowledge/token_store.py).

Este módulo é a variante que armazena timestamps como strings ISO na tabela
``tokens`` (active INTEGER). Coberto com um fake in-memory de psycopg2, sem
banco real. Ver conftest para a store principal (src/db).
"""

from __future__ import annotations

import json
import re
from typing import Any

import psycopg2
import psycopg2.pool
import pytest

from src.knowledge import token_store as ks

_COLUMNS = [
    "id",
    "token",
    "token_prefix",
    "user_id",
    "name",
    "email",
    "role",
    "scopes",
    "environment",
    "tenant_id",
    "active",
    "created_at",
    "last_used_at",
    "expires_at",
]


class _DB:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []
        self._id = 1

    def next_id(self) -> int:
        v = self._id
        self._id += 1
        return v


class _Cursor:
    def __init__(self, db: _DB, row_dict: bool) -> None:
        self._db = db
        self._row_dict = row_dict
        self._result: list[Any] = []
        self.rowcount = -1

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    def _out(self, row, cols):
        if self._row_dict:
            return {c: row[c] for c in cols}
        return tuple(row[c] for c in cols)

    def _cols(self, q):
        m = re.match(r"(?i)\s*select\s+(.*?)\s+from\s+tokens", q)
        assert m, q
        raw = m.group(1).strip()
        return list(_COLUMNS) if raw == "*" else [c.strip() for c in raw.split(",")]

    def execute(self, query, params=None):
        q = " ".join(query.split())
        ql = q.lower()
        params = params or ()
        if ql.startswith("create table") or ql.startswith("create index"):
            return
        if ql.startswith("insert into tokens"):
            self._insert(params)
            return
        if ql.startswith("select"):
            self._select(q, ql, params)
            return
        if ql.startswith("update tokens set active = 0"):
            self._revoke(ql, params)
            return
        if ql.startswith("update tokens set last_used_at"):
            now, uid = params
            for r in self._db.rows:
                if r["user_id"] == uid and r["active"] == 1:
                    r["last_used_at"] = now
            return
        raise AssertionError(f"SQL não suportado: {q!r}")

    def _insert(self, params):
        (
            token_hash,
            token_prefix,
            user_id,
            name,
            email,
            role,
            scopes_json,
            environment,
            tenant_id,
            created_at,
            expires_at,
        ) = params
        if any(r["token"] == token_hash for r in self._db.rows):
            raise psycopg2.IntegrityError("duplicate token")
        self._db.rows.append(
            {
                "id": self._db.next_id(),
                "token": token_hash,
                "token_prefix": token_prefix,
                "user_id": user_id,
                "name": name,
                "email": email,
                "role": role,
                "scopes": scopes_json,
                "environment": environment,
                "tenant_id": tenant_id,
                "active": 1,
                "created_at": created_at,
                "last_used_at": None,
                "expires_at": expires_at,
            }
        )

    def _select(self, q, ql, params):
        if "where token_prefix = %s and active = 1" in ql:
            prefix = params[0]
            rows = [r for r in self._db.rows if r["token_prefix"] == prefix and r["active"] == 1]
        elif "where user_id = %s and active = 1" in ql:
            uid = params[0]
            rows = [r for r in self._db.rows if r["user_id"] == uid and r["active"] == 1]
        elif "from tokens" in ql:
            rows = list(self._db.rows)
            if "where active = 1" in ql:
                rows = [r for r in rows if r["active"] == 1]
            rows.sort(key=lambda r: r["created_at"], reverse=True)
            limit, offset = params[-2], params[-1]
            rows = rows[offset : offset + limit]
        else:
            raise AssertionError(q)
        cols = self._cols(q)
        self._result = [self._out(r, cols) for r in rows]

    def _revoke(self, ql, params):
        if "where user_id = %s and active = 1" in ql:
            uid = params[0]
            n = 0
            for r in self._db.rows:
                if r["user_id"] == uid and r["active"] == 1:
                    r["active"] = 0
                    n += 1
            self.rowcount = n
        elif "where id = %s" in ql:
            rid = params[0]
            for r in self._db.rows:
                if r["id"] == rid:
                    r["active"] = 0
        else:
            raise AssertionError(ql)

    def fetchall(self):
        return list(self._result)

    def fetchone(self):
        return self._result[0] if self._result else None


class _Conn:
    def __init__(self, db):
        self._db = db

    def cursor(self, cursor_factory=None):
        return _Cursor(self._db, cursor_factory is not None)

    def commit(self):
        return None

    def rollback(self):
        return None


class _Pool:
    def __init__(self, *a, **k):
        self._db = _DB()
        self._conn = _Conn(self._db)

    def getconn(self):
        return self._conn

    def putconn(self, conn):
        return None

    def closeall(self):
        return None


@pytest.fixture()
def kstore(monkeypatch):
    monkeypatch.setattr(psycopg2.pool, "ThreadedConnectionPool", _Pool)
    return ks.TokenStore("postgresql://fake/db")


class TestKnowledgeTokenStore:
    def test_register_and_validate(self, kstore):
        rec = kstore.register(name="Alice", email="alice@test.com")
        v = kstore.validate(rec["token"])
        assert v is not None
        assert v["name"] == "Alice"

    def test_invalid_token(self, kstore):
        assert kstore.validate("nope-nope") is None

    def test_revoke_by_user_id(self, kstore):
        rec = kstore.register(name="Bob", email="bob@test.com")
        res = kstore.revoke(rec["user_id"])
        assert res["revoked"] is True
        assert kstore.validate(rec["token"]) is None

    def test_revoke_by_token(self, kstore):
        rec = kstore.register(name="Carol", email="carol@test.com")
        res = kstore.revoke(rec["token"])
        assert res["revoked"] is True

    def test_revoke_missing(self, kstore):
        res = kstore.revoke("does-not-exist")
        assert res["revoked"] is False

    def test_rotate(self, kstore):
        rec = kstore.register(name="Dave", email="dave@test.com", scopes=["deploy"])
        new = kstore.rotate(rec["user_id"])
        assert kstore.validate(rec["token"]) is None
        assert kstore.validate(new["token"]) is not None

    def test_rotate_missing_raises(self, kstore):
        with pytest.raises(ks.TokenStoreError):
            kstore.rotate("ghost")

    def test_touch(self, kstore):
        rec = kstore.register(name="F", email="f@test.com")
        kstore.touch(rec["user_id"])
        v = kstore.validate(rec["token"])
        assert v["last_used_at"] is not None

    def test_list_all_excludes_revoked(self, kstore):
        kstore.register(name="A", email="a@test.com")
        b = kstore.register(name="B", email="b@test.com")
        kstore.revoke(b["token"])
        names = [r["name"] for r in kstore.list_all()]
        assert "A" in names and "B" not in names

    def test_list_all_include_revoked(self, kstore):
        rec = kstore.register(name="A", email="a@test.com")
        kstore.revoke(rec["token"])
        assert any(r["name"] == "A" for r in kstore.list_all(include_revoked=True))

    def test_list_all_scopes_parsed(self, kstore):
        kstore.register(name="G", email="g@test.com", scopes=["qa", "deploy"])
        rec = kstore.list_all()[0]
        assert rec["scopes"] == ["qa", "deploy"]

    def test_expired_token_invalid(self, kstore):
        rec = kstore.register(name="Exp", email="exp@test.com", expires_in_days=-1)
        assert kstore.validate(rec["token"]) is None

    def test_close(self, kstore):
        # closeall não deve levantar
        kstore._pool.closeall()

    def test_register_serializes_scopes_json(self, kstore):
        rec = kstore.register(name="J", email="j@test.com", scopes=["x"])
        v = kstore.validate(rec["token"])
        assert json.loads(v["scopes"]) == ["x"]
