"""Fixtures para testes do dev-twin-mcp-server.

Os testes são **herméticos**: nenhuma conexão PostgreSQL real é aberta. O
`TokenStore` de produção (``src.db.token_store``) usa ``psycopg2`` — aqui o
``ThreadedConnectionPool`` é substituído por um fake in-memory que implementa
exatamente o SQL emitido pela store (register/validate/revoke/rotate/touch/
list_all). Assim exercitamos o código que efetivamente roda em produção sem
depender de um banco.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

# Garante que a raiz do dev-twin-mcp-server esteja no sys.path (permite `from src...`
# mesmo quando o pytest é invocado de outro cwd, sem depender de `pip install -e .`).
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import psycopg2
import psycopg2.pool
import pytest

from src.config.settings import DevTwinSettings
from src.db.token_store import TokenStore

# Colunas na ordem em que a tabela agent_tokens é declarada.
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


class _FakeDB:
    """Backend in-memory compartilhado por todas as conexões do pool fake."""

    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []
        self._next_id = 1

    def next_id(self) -> int:
        v = self._next_id
        self._next_id += 1
        return v


class _FakeCursor:
    """Cursor fake que interpreta o SQL da TokenStore por casamento de padrões."""

    def __init__(self, db: _FakeDB, row_dict: bool) -> None:
        self._db = db
        self._row_dict = row_dict
        self._result: list[Any] = []
        self.rowcount = -1

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    # -- helpers -------------------------------------------------------- #
    def _row_out(self, row: dict[str, Any], columns: list[str]) -> Any:
        if self._row_dict:
            # RealDictCursor devolve dict; SELECT * devolve todas as colunas.
            return {c: row[c] for c in columns}
        # cursor comum devolve tupla na ordem das colunas do SELECT.
        return tuple(row[c] for c in columns)

    def execute(self, query: str, params: tuple | None = None) -> None:
        q = " ".join(query.split())  # normaliza whitespace
        params = params or ()
        ql = q.lower()

        # CREATE TABLE / CREATE INDEX → no-op
        if ql.startswith("create table") or ql.startswith("create index"):
            self._result = []
            self.rowcount = -1
            return

        if ql.startswith("insert into agent_tokens"):
            self._insert(params)
            return

        if ql.startswith("select"):
            self._select(q, ql, params)
            return

        if ql.startswith("update agent_tokens set active = false"):
            self._revoke(ql, params)
            return

        if ql.startswith("update agent_tokens set last_used_at"):
            self._touch(params)
            return

        raise AssertionError(f"SQL não suportado pelo fake cursor: {q!r}")

    # -- operações ------------------------------------------------------ #
    def _insert(self, params: tuple) -> None:
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
        # UNIQUE(token) — replica a IntegrityError do PG.
        if any(r["token"] == token_hash for r in self._db.rows):
            raise psycopg2.IntegrityError("duplicate key value violates unique constraint")
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
                "active": True,
                "created_at": created_at,
                "last_used_at": None,
                "expires_at": expires_at,
            }
        )
        self.rowcount = 1

    def _select(self, q: str, ql: str, params: tuple) -> None:
        # validate() / revoke() fallback / rotate(): filtra por prefix ou user_id.
        if "where token_prefix = %s and active = true" in ql:
            prefix = params[0]
            rows = [r for r in self._db.rows if r["token_prefix"] == prefix and r["active"] is True]
            cols = self._select_columns(q)
            self._result = [self._row_out(r, cols) for r in rows]
            return

        if "where user_id = %s and active = true" in ql:
            uid = params[0]
            rows = [r for r in self._db.rows if r["user_id"] == uid and r["active"] is True]
            cols = self._select_columns(q)
            self._result = [self._row_out(r, cols) for r in rows]
            return

        # list_all(): com ou sem filtro active, ORDER BY created_at DESC LIMIT/OFFSET.
        if "from agent_tokens" in ql:
            rows = list(self._db.rows)
            if "where active = true" in ql:
                rows = [r for r in rows if r["active"] is True]
            rows.sort(key=lambda r: r["created_at"], reverse=True)
            limit = params[-2] if len(params) >= 2 else len(rows)
            offset = params[-1] if len(params) >= 2 else 0
            rows = rows[offset : offset + limit]
            cols = self._select_columns(q)
            self._result = [self._row_out(r, cols) for r in rows]
            return

        raise AssertionError(f"SELECT não suportado pelo fake cursor: {q!r}")

    def _select_columns(self, q: str) -> list[str]:
        m = re.match(r"(?i)\s*select\s+(.*?)\s+from\s+agent_tokens", q)
        assert m, f"não consegui extrair colunas de: {q!r}"
        cols_raw = m.group(1).strip()
        if cols_raw == "*":
            return list(_COLUMNS)
        return [c.strip() for c in cols_raw.split(",")]

    def _revoke(self, ql: str, params: tuple) -> None:
        if "where user_id = %s and active = true" in ql:
            uid = params[0]
            affected = 0
            for r in self._db.rows:
                if r["user_id"] == uid and r["active"] is True:
                    r["active"] = False
                    affected += 1
            self.rowcount = affected
            return
        if "where id = %s" in ql:
            rid = params[0]
            affected = 0
            for r in self._db.rows:
                if r["id"] == rid:
                    r["active"] = False
                    affected += 1
            self.rowcount = affected
            return
        raise AssertionError(f"UPDATE(revoke) não suportado: {ql!r}")

    def _touch(self, params: tuple) -> None:
        now, uid = params
        affected = 0
        for r in self._db.rows:
            if r["user_id"] == uid and r["active"] is True:
                r["last_used_at"] = now
                affected += 1
        self.rowcount = affected

    # -- fetch ---------------------------------------------------------- #
    def fetchall(self) -> list[Any]:
        return list(self._result)

    def fetchone(self) -> Any:
        return self._result[0] if self._result else None


class _FakeConnection:
    def __init__(self, db: _FakeDB) -> None:
        self._db = db

    def cursor(self, cursor_factory: Any = None) -> _FakeCursor:
        row_dict = cursor_factory is not None
        return _FakeCursor(self._db, row_dict)

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None

    def close(self) -> None:
        return None


class _FakePool:
    """Substituto de psycopg2.pool.ThreadedConnectionPool — 100% in-memory."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        self._db = _FakeDB()
        self._conn = _FakeConnection(self._db)

    def getconn(self) -> _FakeConnection:
        return self._conn

    def putconn(self, conn: _FakeConnection) -> None:
        return None

    def closeall(self) -> None:
        return None


@pytest.fixture()
def settings() -> DevTwinSettings:
    return DevTwinSettings(
        pg_host="fake",
        pg_db="fake",
        pg_user="fake",
        pg_password="fake",
        admin_token="admin-secret-token-for-tests",
    )


@pytest.fixture()
def store(monkeypatch, settings: DevTwinSettings) -> TokenStore:
    """TokenStore de produção com o pool psycopg2 trocado por um fake in-memory."""
    monkeypatch.setattr(psycopg2.pool, "ThreadedConnectionPool", _FakePool)
    return TokenStore(settings)


@pytest.fixture()
def admin_token() -> str:
    return "admin-secret-token-for-tests"
