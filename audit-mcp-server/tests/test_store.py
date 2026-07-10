"""Testes herméticos para ``AuditStore`` (código SQL real, psycopg2 mockado).

O pool psycopg2 é substituído por um fake em memória que interpreta os
comandos SQL emitidos pelo store, exercitando o código real de
serialização/desserialização (json.dumps/loads, RealDictCursor) sem
nenhum PostgreSQL de verdade.
"""

import pytest

from src.db.store import AuditStore


class FakeCursor:
    """Cursor que interpreta os SQLs emitidos por ``AuditStore``."""

    def __init__(self, table: dict, cursor_factory=None):
        self._table = table
        self._factory = cursor_factory
        self._result: list[dict] | None = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, query: str, params=None) -> None:
        params = params or ()
        q = " ".join(query.split())  # normaliza espaços

        if q.startswith("INSERT INTO audit_log"):
            (
                audit_id,
                service,
                repo,
                env,
                criticality,
                score,
                passed,
                status,
                checklist_json,
            ) = params
            self._table[audit_id] = {
                "id": audit_id,
                "service": service,
                "repo": repo,
                "env": env,
                "criticality": criticality,
                "score": score,
                "passed": passed,
                "status": status,
                "checklist": checklist_json,
                "created_at": "2026-01-01T00:00:00+00:00",
                "updated_at": "2026-01-01T00:00:00+00:00",
            }
            self._result = [{"id": audit_id}]
        elif q.startswith("SELECT * FROM audit_log WHERE id ="):
            row = self._table.get(params[0])
            self._result = [dict(row)] if row else []
        elif q.startswith("SELECT * FROM audit_log WHERE service ="):
            service, env = params
            rows = [dict(r) for r in self._table.values() if r["service"] == service and r["env"] == env]
            self._result = rows[:1]
        elif q.startswith("SELECT * FROM audit_log WHERE 1=1"):
            self._result = [dict(r) for r in self._table.values()]
        elif q.startswith("SELECT checklist FROM audit_log WHERE id ="):
            row = self._table.get(params[0])
            self._result = [{"checklist": row["checklist"]}] if row else []
        elif q.startswith("UPDATE audit_log SET status ="):
            status, score, passed, audit_id = params
            if audit_id in self._table:
                self._table[audit_id].update(status=status, score=score, passed=passed)
            self._result = []
        elif q.startswith("UPDATE audit_log SET checklist ="):
            checklist_json, audit_id = params
            if audit_id in self._table:
                self._table[audit_id]["checklist"] = checklist_json
            self._result = []
        else:  # pragma: no cover - guarda contra SQL não previsto no teste
            raise AssertionError(f"SQL inesperado: {q}")

    def fetchone(self):
        return self._result[0] if self._result else None

    def fetchall(self):
        return list(self._result or [])


class FakeConnection:
    def __init__(self, table: dict):
        self._table = table
        self.committed = False
        self.rolled_back = False

    def cursor(self, cursor_factory=None):
        return FakeCursor(self._table, cursor_factory)

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


class FakePool:
    def __init__(self, *args, **kwargs):
        self._table: dict = {}
        self._conn = FakeConnection(self._table)
        self.closed = False

    def getconn(self):
        return self._conn

    def putconn(self, conn):
        pass

    def closeall(self):
        self.closed = True


@pytest.fixture
def real_store(settings, monkeypatch):
    """``AuditStore`` real com pool psycopg2 mockado."""
    monkeypatch.setattr("psycopg2.pool.ThreadedConnectionPool", FakePool)
    store = AuditStore(settings=settings)
    yield store
    store.close()


def test_create_audit(real_store):
    """Testa criação de auditoria."""
    audit_id = real_store.create_audit(
        service="test-service",
        repo="test-repo",
        env="dev",
        criticality="medium",
        score=0.75,
        passed=True,
        status="approved",
        checklist={"items": []},
    )
    assert audit_id.startswith("audit_")
    assert len(audit_id) > 10


def test_get_audit(real_store):
    """Testa leitura de auditoria (com desserialização do checklist JSON)."""
    audit_id = real_store.create_audit(
        service="test",
        repo="test-repo",
        env="dev",
        criticality="low",
        score=0.8,
        passed=True,
        status="approved",
        checklist={"foo": "bar"},
    )
    audit = real_store.get_audit(audit_id)
    assert audit is not None
    assert audit["service"] == "test"
    assert audit["score"] == 0.8
    assert audit["passed"] is True
    assert audit["checklist"] == {"foo": "bar"}


def test_get_audit_not_found(real_store):
    """Auditoria inexistente retorna None."""
    assert real_store.get_audit("audit_missing_dev") is None


def test_get_latest_audit(real_store):
    """get_latest_audit retorna a auditoria do serviço/env."""
    real_store.create_audit(
        service="svc",
        repo="r",
        env="prod",
        criticality="high",
        score=0.9,
        passed=True,
        status="approved",
        checklist={},
    )
    latest = real_store.get_latest_audit("svc", "prod")
    assert latest is not None
    assert latest["service"] == "svc"
    assert real_store.get_latest_audit("svc", "dev") is None


def test_list_audits_with_filters(real_store):
    """list_audits filtra e desserializa."""
    real_store.create_audit(
        service="a",
        repo="r",
        env="dev",
        criticality="medium",
        score=0.5,
        passed=False,
        status="pending_approval",
        checklist={"items": [{"name": "x"}]},
    )
    audits = real_store.list_audits()
    assert len(audits) == 1
    assert audits[0]["checklist"] == {"items": [{"name": "x"}]}
    assert audits[0]["passed"] is False


def test_update_audit_status(real_store):
    """update_audit_status muda status/score/passed."""
    audit_id = real_store.create_audit(
        service="svc",
        repo="r",
        env="dev",
        criticality="medium",
        score=0.0,
        passed=False,
        status="pending_approval",
        checklist={},
    )
    real_store.update_audit_status(audit_id, "approved", 0.95, True)
    audit = real_store.get_audit(audit_id)
    assert audit["status"] == "approved"
    assert audit["score"] == 0.95


def test_add_audit_item(real_store):
    """Testa adição de itens do checklist (JSON round-trip)."""
    audit_id = real_store.create_audit(
        service="test",
        repo="repo",
        env="dev",
        criticality="medium",
        score=0.0,
        passed=False,
        status="pending_approval",
        checklist={},
    )
    real_store.add_audit_item(
        audit_id=audit_id,
        category="structure",
        name="has_src_dir",
        required=True,
        passed=True,
        details="ok",
    )
    items = real_store.get_audit_items(audit_id)
    assert len(items) == 1
    assert items[0]["name"] == "has_src_dir"
    assert items[0]["details"] == "ok"


def test_get_audit_items_empty(real_store):
    """Auditoria sem items retorna lista vazia."""
    audit_id = real_store.create_audit(
        service="s",
        repo="r",
        env="dev",
        criticality="medium",
        score=0.0,
        passed=False,
        status="pending_approval",
        checklist={},
    )
    assert real_store.get_audit_items(audit_id) == []


def test_add_and_get_approvals(real_store):
    """Aprovações são persistidas no checklist JSON."""
    audit_id = real_store.create_audit(
        service="s",
        repo="r",
        env="dev",
        criticality="medium",
        score=0.8,
        passed=True,
        status="pending_approval",
        checklist={},
    )
    real_store.add_approval(audit_id, "alice", "approved", role="lead", notes="lgtm")
    approvals = real_store.get_approvals(audit_id)
    assert len(approvals) == 1
    assert approvals[0]["approved_by"] == "alice"
    assert approvals[0]["role"] == "lead"
    assert real_store.get_approvals("audit_missing_dev") == []


def test_service_criticality(real_store):
    """set_service_criticality não persiste; get retorna sempre medium."""
    real_store.set_service_criticality("my-service", "high", "admin")
    assert real_store.get_service_criticality("my-service") == "medium"
    assert real_store.get_service_criticality("unknown-service") == "medium"


def test_conn_rollback_on_error(settings, monkeypatch):
    """Erro dentro do context manager dispara rollback e propaga."""
    monkeypatch.setattr("psycopg2.pool.ThreadedConnectionPool", FakePool)
    store = AuditStore(settings=settings)
    conn = store._pool.getconn()

    def boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(conn, "cursor", boom)
    with pytest.raises(RuntimeError):
        store.get_audit("x")
    assert conn.rolled_back is True
    store.close()


def test_dsn_property(settings):
    """pg_dsn compõe a connection string."""
    dsn = settings.pg_dsn
    assert "host=localhost" in dsn
    assert "dbname=app" in dsn
