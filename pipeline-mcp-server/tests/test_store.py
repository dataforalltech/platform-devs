"""Testes do PipelineStore (src/db/store.py) com psycopg2 mockado.

Nada toca um PostgreSQL real: o `ThreadedConnectionPool` é substituído por um
fake que devolve conexões/cursores controlados. Assim exercitamos a lógica de
montagem de SQL, mapeamento de linhas (`_pipeline_row`) e o comportamento de
commit/rollback do context manager `_get_conn`, de forma hermética.
"""

from __future__ import annotations

import json
from typing import Any

import psycopg2.pool
import pytest

from src.db import store as store_mod
from src.db.store import DEFAULT_GATES, VALID_ENVS, VALID_GATE_TYPES, PipelineStore, _pipeline_row


class FakeCursor:
    """Cursor controlável: guarda SQL executado e devolve resultados scriptados."""

    def __init__(self, shared: dict[str, Any]) -> None:
        self._shared = shared
        self.executed: list[tuple[str, Any]] = []
        self._fetchone_queue: list[Any] = shared.setdefault("fetchone", [])
        self._fetchall_queue: list[Any] = shared.setdefault("fetchall", [])
        self.rowcount = shared.get("rowcount", 0)

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, *exc: Any) -> bool:
        return False

    def execute(self, sql: str, params: Any = None) -> None:
        self.executed.append((sql, params))
        self._shared.setdefault("all_sql", []).append(sql)
        self._shared.setdefault("executes", []).append((sql, params))

    def fetchone(self) -> Any:
        if self._fetchone_queue:
            return self._fetchone_queue.pop(0)
        return None

    def fetchall(self) -> Any:
        if self._fetchall_queue:
            return self._fetchall_queue.pop(0)
        return []


class FakeConn:
    def __init__(self, shared: dict[str, Any]) -> None:
        self._shared = shared
        self.committed = False
        self.rolled_back = False

    def cursor(self, cursor_factory: Any = None) -> FakeCursor:
        return FakeCursor(self._shared)

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True


class FakePool:
    def __init__(self, shared: dict[str, Any]) -> None:
        self._shared = shared
        self.conns: list[FakeConn] = []
        self.closed = False

    def getconn(self) -> FakeConn:
        conn = FakeConn(self._shared)
        self.conns.append(conn)
        return conn

    def putconn(self, conn: FakeConn) -> None:
        pass

    def closeall(self) -> None:
        self.closed = True


@pytest.fixture
def shared() -> dict[str, Any]:
    return {}


@pytest.fixture
def pool_factory(monkeypatch, shared):
    """Substitui ThreadedConnectionPool por um FakePool que compartilha 'shared'."""
    created: dict[str, FakePool] = {}

    def _make(*args: Any, **kwargs: Any) -> FakePool:
        pool = FakePool(shared)
        created["pool"] = pool
        return pool

    monkeypatch.setattr(psycopg2.pool, "ThreadedConnectionPool", _make)
    return created


@pytest.fixture
def store(pool_factory, shared) -> PipelineStore:
    # __init__ roda _migrate() (só CREATE TABLE, nenhum fetch necessário)
    return PipelineStore()


# ─────────────────────────────────────────────────────────────────────────── #
# init + migrate + close                                                       #
# ─────────────────────────────────────────────────────────────────────────── #
def test_init_runs_migrations(store, shared):
    sql_joined = " ".join(shared.get("all_sql", []))
    assert "CREATE TABLE IF NOT EXISTS pipelines" in sql_joined
    assert "CREATE TABLE IF NOT EXISTS promotions" in sql_joined
    assert "CREATE TABLE IF NOT EXISTS gates" in sql_joined


def test_close_closes_pool(store, pool_factory):
    store.close()
    assert pool_factory["pool"].closed is True


def test_get_conn_commits_on_success(store, shared):
    with store._get_conn() as conn:
        assert conn is not None
    assert conn.committed is True


def test_get_conn_rolls_back_on_error(store):
    with pytest.raises(ValueError):
        with store._get_conn() as conn:
            raise ValueError("boom")
    assert conn.rolled_back is True


# ─────────────────────────────────────────────────────────────────────────── #
# register / get / list                                                        #
# ─────────────────────────────────────────────────────────────────────────── #
def test_register_pipeline_created(store, shared):
    # SELECT existing → None; final SELECT → row inserido
    row = {
        "service": "svc",
        "repo": "org/svc",
        "base_branch": "develop",
        "current_env": "dev",
        "blocked": 0,
        "gates_config": json.dumps(DEFAULT_GATES),
        "registered_at": "t",
        "updated_at": "t",
    }
    shared["fetchone"] = [None, row]
    result = store.register_pipeline("svc", "org/svc")
    assert result["action"] == "created"
    # gates_config foi desserializado para dict por _pipeline_row
    assert result["pipeline"]["gates_config"] == DEFAULT_GATES
    inserts = [s for s in shared["all_sql"] if "INSERT INTO pipelines" in s]
    assert len(inserts) == 1


def test_register_pipeline_updated(store, shared):
    existing = {"service": "svc"}
    row = {"service": "svc", "repo": "org/new", "gates_config": "{}"}
    shared["fetchone"] = [existing, row]
    result = store.register_pipeline("svc", "org/new", base_branch="trunk")
    assert result["action"] == "updated"
    assert any("UPDATE pipelines" in s for s in shared["all_sql"])


def test_get_pipeline_none(store, shared):
    shared["fetchone"] = [None]
    assert store.get_pipeline("ghost") is None


def test_get_pipeline_with_promotions(store, shared):
    shared["fetchone"] = [{"service": "svc", "gates_config": "{}"}]
    shared["fetchall"] = [[{"id": 1, "service": "svc"}]]
    result = store.get_pipeline("svc")
    assert result["service"] == "svc"
    assert result["recent_promotions"] == [{"id": 1, "service": "svc"}]


def test_list_pipelines_no_filter(store, shared):
    shared["fetchall"] = [[{"service": "a", "gates_config": "{}"}]]
    result = store.list_pipelines()
    assert len(result) == 1
    assert "WHERE 1=1" in shared["all_sql"][-1]


def test_list_pipelines_env_and_status_active(store, shared):
    shared["fetchall"] = [[]]
    store.list_pipelines(env="homol", status="active")
    sql = shared["all_sql"][-1]
    assert "current_env=%s" in sql
    assert "blocked=0" in sql


def test_list_pipelines_status_blocked(store, shared):
    shared["fetchall"] = [[]]
    store.list_pipelines(status="blocked")
    assert "blocked=1" in shared["all_sql"][-1]


# ─────────────────────────────────────────────────────────────────────────── #
# update env / block / gates config                                            #
# ─────────────────────────────────────────────────────────────────────────── #
def test_update_pipeline_env(store, shared):
    store.update_pipeline_env("svc", "homol", version="v1")
    sql, params = shared_last_execute(shared)
    assert "UPDATE pipelines SET current_env" in sql
    assert params == ("homol", "v1", params[2], "svc")


def test_block_pipeline(store, shared):
    shared["fetchone"] = [{"service": "svc", "blocked": 1, "gates_config": "{}"}]
    result = store.block_pipeline("svc", "reason", "admin")
    assert result["blocked"] == 1
    assert any("SET blocked=1" in s for s in shared["all_sql"])


def test_block_pipeline_missing_row(store, shared):
    shared["fetchone"] = [None]
    assert store.block_pipeline("svc", "r", "a") == {}


def test_set_gates_config(store, shared):
    shared["fetchone"] = [{"service": "svc", "gates_config": json.dumps({"homol": ["qa_tests"]})}]
    result = store.set_gates_config("svc", {"homol": ["qa_tests"]})
    assert result["gates_config"] == {"homol": ["qa_tests"]}


def test_set_gates_config_missing_row(store, shared):
    shared["fetchone"] = [None]
    assert store.set_gates_config("svc", {}) == {}


# ─────────────────────────────────────────────────────────────────────────── #
# promotions                                                                   #
# ─────────────────────────────────────────────────────────────────────────── #
def test_add_promotion_returns_id(store, shared):
    shared["fetchone"] = [(42,)]  # RETURNING id → tupla
    pid = store.add_promotion(
        service="svc",
        from_env="dev",
        to_env="homol",
        promoted_by="u",
        reason="r",
        gates_snapshot={"qa_tests": True},
        deploy_ref="homol",
        status="pending",
        pr_number=7,
        pr_url="u",
    )
    assert pid == 42
    assert any("INSERT INTO promotions" in s for s in shared["all_sql"])


def test_complete_promotion(store, shared):
    store.complete_promotion(5, "success")
    sql, params = shared_last_execute(shared)
    assert "UPDATE promotions SET status" in sql
    assert params[0] == "success"
    assert params[-1] == 5


def test_approve_promotion(store, shared):
    shared["fetchone"] = [{"id": 5, "status": "approved"}]
    result = store.approve_promotion(5, "bob")
    assert result["status"] == "approved"
    assert any("status='approved'" in s for s in shared["all_sql"])


def test_approve_promotion_missing(store, shared):
    shared["fetchone"] = [None]
    assert store.approve_promotion(5, "bob") is None


def test_get_promotion(store, shared):
    shared["fetchone"] = [{"id": 3, "service": "svc"}]
    assert store.get_promotion(3)["service"] == "svc"


def test_get_promotion_missing(store, shared):
    shared["fetchone"] = [None]
    assert store.get_promotion(3) is None


def test_get_promotion_history_with_service(store, shared):
    shared["fetchall"] = [[{"id": 1}, {"id": 2}]]
    result = store.get_promotion_history(service="svc", limit=5)
    assert len(result) == 2
    sql = shared["all_sql"][-1]
    assert "WHERE service=%s" in sql


def test_get_promotion_history_all(store, shared):
    shared["fetchall"] = [[]]
    store.get_promotion_history()
    sql = shared["all_sql"][-1]
    assert "WHERE service" not in sql
    assert "ORDER BY created_at DESC" in sql


# ─────────────────────────────────────────────────────────────────────────── #
# gates                                                                        #
# ─────────────────────────────────────────────────────────────────────────── #
def test_upsert_gate_passed_true(store, shared):
    shared["fetchone"] = [{"service": "svc", "gate_type": "qa_tests", "passed": 1}]
    result = store.upsert_gate("svc", "dev", "qa_tests", True, details="ok", evaluated_by="ci")
    assert result["passed"] == 1
    # confere que passed foi convertido para 1 nos params do INSERT
    insert = next(e for e in shared_all_executes(shared) if "INSERT INTO gates" in e[0])
    assert insert[1][3] == 1


def test_upsert_gate_passed_false(store, shared):
    shared["fetchone"] = [{"passed": 0}]
    store.upsert_gate("svc", "dev", "qa_tests", False)
    insert = next(e for e in shared_all_executes(shared) if "INSERT INTO gates" in e[0])
    assert insert[1][3] == 0


def test_upsert_gate_missing_row(store, shared):
    shared["fetchone"] = [None]
    assert store.upsert_gate("svc", "dev", "qa_tests", True) == {}


def test_get_gates(store, shared):
    shared["fetchall"] = [[{"gate_type": "qa_tests", "passed": 1}]]
    result = store.get_gates("svc", "dev")
    assert result[0]["gate_type"] == "qa_tests"


def test_clear_gates_returns_rowcount(store, shared):
    shared["rowcount"] = 3
    deleted = store.clear_gates("svc", "dev")
    assert deleted == 3
    assert any("DELETE FROM gates" in s for s in shared["all_sql"])


# ─────────────────────────────────────────────────────────────────────────── #
# overview                                                                     #
# ─────────────────────────────────────────────────────────────────────────── #
def test_get_pipeline_overview(store, shared):
    # 1º fetchall: contagem por env/blocked; 2º fetchall: gates com falha
    shared["fetchall"] = [
        [
            {"current_env": "dev", "blocked": 0, "cnt": 2},
            {"current_env": "dev", "blocked": 1, "cnt": 1},
            {"current_env": "homol", "blocked": 0, "cnt": 1},
        ],
        [{"service": "svc", "env": "dev", "failed": 1}],
    ]
    result = store.get_pipeline_overview()
    assert result["total_services"] == 4
    assert result["by_env"]["dev"] == {"total": 3, "blocked": 1, "active": 2}
    assert result["by_env"]["homol"] == {"total": 1, "blocked": 0, "active": 1}
    assert result["services_with_failed_gates"] == [{"service": "svc", "env": "dev", "failed": 1}]


# ─────────────────────────────────────────────────────────────────────────── #
# _pipeline_row + constantes                                                   #
# ─────────────────────────────────────────────────────────────────────────── #
def test_pipeline_row_parses_gates_config():
    row = {"service": "svc", "gates_config": json.dumps({"homol": ["qa_tests"]})}
    assert _pipeline_row(row)["gates_config"] == {"homol": ["qa_tests"]}


def test_pipeline_row_invalid_json_defaults_empty():
    row = {"service": "svc", "gates_config": "not-json{"}
    assert _pipeline_row(row)["gates_config"] == {}


def test_pipeline_row_empty():
    assert _pipeline_row({}) == {}


def test_now_is_iso():
    assert "T" in store_mod._now()


def test_default_gates_and_valid_sets():
    assert "audit_compliance" in DEFAULT_GATES["dev"]
    assert "prod" in DEFAULT_GATES
    assert "rollback" in VALID_ENVS
    assert "qa_tests" in VALID_GATE_TYPES


# ── helpers ──────────────────────────────────────────────────────────────── #
def shared_all_executes(shared: dict[str, Any]) -> list[tuple[str, Any]]:
    """Reconstrói (sql, params) — só temos all_sql; params exigem re-execução.

    FakeCursor não guarda params globalmente, então usamos o último cursor.
    Para simplicidade, reexpomos via 'executes' preenchido em execute().
    """
    return shared.get("executes", [])


def shared_last_execute(shared: dict[str, Any]) -> tuple[str, Any]:
    execs = shared.get("executes", [])
    return execs[-1] if execs else ("", None)
