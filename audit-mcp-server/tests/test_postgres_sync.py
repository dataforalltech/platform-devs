"""Testes herméticos para AuditPostgresSync (adapter mockado, sem PostgreSQL)."""

from unittest.mock import MagicMock

import pytest

from src.db.postgres_sync import AuditPostgresSync


@pytest.fixture
def disabled_sync():
    """Sync com PostgreSQL desabilitado (nenhum adapter é criado)."""
    return AuditPostgresSync(postgres_config={}, enabled=False)


@pytest.fixture
def active_sync():
    """Sync ativo com adapter mockado.

    Instancia desabilitado (evita o import real do adapter) e injeta um mock,
    de modo a exercitar os caminhos ativos de forma hermética.
    """
    sync = AuditPostgresSync(postgres_config={}, enabled=False)
    sync.enabled = True
    sync.adapter = MagicMock()
    return sync


# --------------------------------------------------------------------------- #
# Inicialização
# --------------------------------------------------------------------------- #


def test_init_enabled_import_fails_disables():
    """Com enabled=True mas sem o adapter real, o sync se autodesabilita."""
    sync = AuditPostgresSync(postgres_config={"host": "x"}, enabled=True)
    assert sync.enabled is False
    assert sync.adapter is None


def test_init_disabled(disabled_sync):
    assert disabled_sync.enabled is False
    assert disabled_sync.adapter is None


# --------------------------------------------------------------------------- #
# Caminhos short-circuit (disabled) — devolvem True/None sem tocar adapter
# --------------------------------------------------------------------------- #


def test_disabled_syncs_return_true(disabled_sync):
    assert disabled_sync.sync_audit_created({"id": "a"}) is True
    assert disabled_sync.sync_audit_updated("a", {"status": "approved"}) is True
    assert disabled_sync.sync_audit_item_added("a", {}) is True
    assert disabled_sync.sync_approval_added("a", {}) is True
    assert disabled_sync.sync_service_criticality("s", "high", "u") is True
    assert disabled_sync.log_action("create", "a") is True
    assert disabled_sync.health_check() is True


def test_disabled_queries_return_none(disabled_sync):
    assert disabled_sync.get_audit("a") is None
    assert disabled_sync.list_audits() is None
    assert disabled_sync.get_audit_items("a") is None
    assert disabled_sync.get_approvals("a") is None


def test_disabled_close_is_noop(disabled_sync):
    # adapter é None; close não deve levantar
    disabled_sync.close()


# --------------------------------------------------------------------------- #
# Caminhos ativos (adapter mockado)
# --------------------------------------------------------------------------- #


def test_sync_audit_created_active(active_sync):
    ok = active_sync.sync_audit_created(
        {
            "id": "audit_1",
            "service": "svc",
            "repo": "r",
            "env": "dev",
            "criticality": "medium",
            "score": 0.8,
            "passed": True,
            "status": "approved",
            "checklist": "{}",
        }
    )
    assert ok is True
    active_sync.adapter.sync_to_postgres.assert_called_once()
    table, data = active_sync.adapter.sync_to_postgres.call_args.args
    assert table == "audits"
    assert data["environment"] == "dev"
    assert data["score"] == 0.8


def test_sync_audit_updated_active(active_sync):
    ok = active_sync.sync_audit_updated("audit_1", {"status": "approved", "score": 0.9, "passed": True})
    assert ok is True
    active_sync.adapter.query_postgres.assert_called_once()
    sql, values = active_sync.adapter.query_postgres.call_args.args
    assert "UPDATE audits SET" in sql
    assert "audit_1" in values


def test_sync_audit_updated_no_fields(active_sync):
    """Sem campos conhecidos, não emite UPDATE."""
    ok = active_sync.sync_audit_updated("audit_1", {"irrelevant": 1})
    assert ok is True
    active_sync.adapter.query_postgres.assert_not_called()


def test_sync_audit_item_added_active(active_sync):
    ok = active_sync.sync_audit_item_added(
        "audit_1", {"category": "docs", "name": "has_readme", "passed": True}
    )
    assert ok is True
    table, data = active_sync.adapter.sync_to_postgres.call_args.args
    assert table == "audit_items"
    assert data["name"] == "has_readme"


def test_sync_approval_added_active(active_sync):
    ok = active_sync.sync_approval_added("audit_1", {"approved_by": "alice", "decision": "approved"})
    assert ok is True
    table, data = active_sync.adapter.sync_to_postgres.call_args.args
    assert table == "audit_approvals"
    assert data["approved_by"] == "alice"


def test_sync_service_criticality_active(active_sync):
    ok = active_sync.sync_service_criticality("svc", "high", "admin")
    assert ok is True
    table, data = active_sync.adapter.sync_to_postgres.call_args.args
    assert table == "service_criticality"
    assert data["criticality"] == "high"


def test_get_audit_active_found(active_sync):
    active_sync.adapter.query_postgres.return_value = [{"id": "audit_1", "service": "svc"}]
    result = active_sync.get_audit("audit_1")
    assert result == {"id": "audit_1", "service": "svc"}


def test_get_audit_active_not_found(active_sync):
    active_sync.adapter.query_postgres.return_value = []
    assert active_sync.get_audit("audit_1") is None


def test_list_audits_active_with_filters(active_sync):
    active_sync.adapter.query_postgres.return_value = [{"id": "a"}]
    result = active_sync.list_audits(service="svc", environment="dev")
    assert result == [{"id": "a"}]
    sql, params = active_sync.adapter.query_postgres.call_args.args
    assert "AND service = %s" in sql
    assert "AND environment = %s" in sql
    assert params == ("svc", "dev")


def test_list_audits_active_no_filters(active_sync):
    active_sync.adapter.query_postgres.return_value = []
    active_sync.list_audits()
    sql, params = active_sync.adapter.query_postgres.call_args.args
    assert params is None


def test_get_audit_items_active(active_sync):
    active_sync.adapter.query_postgres.return_value = [{"name": "x"}]
    assert active_sync.get_audit_items("audit_1") == [{"name": "x"}]


def test_get_approvals_active(active_sync):
    active_sync.adapter.query_postgres.return_value = [{"approved_by": "a"}]
    assert active_sync.get_approvals("audit_1") == [{"approved_by": "a"}]


def test_log_action_active(active_sync):
    ok = active_sync.log_action("approve", "audit_1", actor_id=7, details={"k": "v"})
    assert ok is True
    active_sync.adapter.audit_log.assert_called_once()


def test_health_check_active(active_sync):
    active_sync.adapter.health_check.return_value = True
    assert active_sync.health_check() is True


def test_close_active(active_sync):
    active_sync.close()
    active_sync.adapter.close.assert_called_once()


# --------------------------------------------------------------------------- #
# Tratamento de erro (adapter levanta exceção → método devolve False/None)
# --------------------------------------------------------------------------- #


def test_sync_error_returns_false(active_sync):
    active_sync.adapter.sync_to_postgres.side_effect = RuntimeError("db down")
    assert active_sync.sync_audit_created({"id": "a", "service": "s"}) is False


def test_update_error_returns_false(active_sync):
    active_sync.adapter.query_postgres.side_effect = RuntimeError("db down")
    assert active_sync.sync_audit_updated("a", {"status": "x"}) is False


def test_sync_item_error_returns_false(active_sync):
    active_sync.adapter.sync_to_postgres.side_effect = RuntimeError("x")
    assert active_sync.sync_audit_item_added("a", {}) is False


def test_sync_approval_error_returns_false(active_sync):
    active_sync.adapter.sync_to_postgres.side_effect = RuntimeError("x")
    assert active_sync.sync_approval_added("a", {}) is False


def test_sync_criticality_error_returns_false(active_sync):
    active_sync.adapter.sync_to_postgres.side_effect = RuntimeError("x")
    assert active_sync.sync_service_criticality("s", "high", "u") is False


def test_get_audit_error_returns_none(active_sync):
    active_sync.adapter.query_postgres.side_effect = RuntimeError("x")
    assert active_sync.get_audit("a") is None


def test_list_audits_error_returns_none(active_sync):
    active_sync.adapter.query_postgres.side_effect = RuntimeError("x")
    assert active_sync.list_audits() is None


def test_get_audit_items_error_returns_none(active_sync):
    active_sync.adapter.query_postgres.side_effect = RuntimeError("x")
    assert active_sync.get_audit_items("a") is None


def test_get_approvals_error_returns_none(active_sync):
    active_sync.adapter.query_postgres.side_effect = RuntimeError("x")
    assert active_sync.get_approvals("a") is None


def test_log_action_error_returns_false(active_sync):
    active_sync.adapter.audit_log.side_effect = RuntimeError("x")
    assert active_sync.log_action("create", "a") is False


def test_health_check_error_returns_false(active_sync):
    active_sync.adapter.health_check.side_effect = RuntimeError("x")
    assert active_sync.health_check() is False
