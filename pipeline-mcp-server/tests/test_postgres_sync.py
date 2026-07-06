"""Testes do PipelinePostgresSync (src/db/postgres_sync.py).

O adapter PostgreSQL é injetado como mock; nenhum banco real é tocado.
Cobrimos os três estados de cada método: desabilitado (no-op → True),
sucesso (adapter chamado) e exceção (logada → False).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from src.db.postgres_sync import PipelinePostgresSync


@pytest.fixture
def sync() -> PipelinePostgresSync:
    """Sync habilitado com adapter mockado (sem import de template real)."""
    s = PipelinePostgresSync(postgres_config={}, enabled=False)
    s.enabled = True
    s.adapter = MagicMock()
    return s


@pytest.fixture
def disabled_sync() -> PipelinePostgresSync:
    return PipelinePostgresSync(postgres_config={}, enabled=False)


# ─────────────────────────────────────────────────────────────────────────── #
# init                                                                         #
# ─────────────────────────────────────────────────────────────────────────── #
def test_init_disabled_has_no_adapter(disabled_sync):
    assert disabled_sync.enabled is False
    assert disabled_sync.adapter is None


def test_init_enabled_import_failure_disables(monkeypatch):
    # O template não existe no path de teste → import falha → enabled vira False.
    s = PipelinePostgresSync(postgres_config={"host": "x"}, enabled=True)
    assert s.enabled is False
    assert s.adapter is None


def test_close_calls_adapter(sync):
    sync.close()
    sync.adapter.close.assert_called_once()


def test_close_no_adapter_is_safe(disabled_sync):
    disabled_sync.close()  # não deve levantar


# ─────────────────────────────────────────────────────────────────────────── #
# disabled → no-op True                                                        #
# ─────────────────────────────────────────────────────────────────────────── #
class TestDisabledNoOp:
    def test_pipeline_registered(self, disabled_sync):
        assert disabled_sync.sync_pipeline_registered({"service": "s"}) is True

    def test_env_updated(self, disabled_sync):
        assert disabled_sync.sync_pipeline_env_updated("s", "homol") is True

    def test_blocked(self, disabled_sync):
        assert disabled_sync.sync_pipeline_blocked("s", "r", "a") is True

    def test_promotion_created(self, disabled_sync):
        assert (
            disabled_sync.sync_promotion_created(
                {"service": "s", "from_env": "dev", "to_env": "homol"}
            )
            is True
        )

    def test_promotion_completed(self, disabled_sync):
        assert disabled_sync.sync_promotion_completed(1, "success") is True

    def test_promotion_approved(self, disabled_sync):
        assert disabled_sync.sync_promotion_approved(1, "a", "t") is True

    def test_gate_evaluated(self, disabled_sync):
        assert disabled_sync.sync_gate_evaluated("s", "dev", "qa_tests", True) is True

    def test_get_pipeline_none(self, disabled_sync):
        assert disabled_sync.get_pipeline("s") is None

    def test_list_promotions_none(self, disabled_sync):
        assert disabled_sync.list_promotions() is None

    def test_get_gates_none(self, disabled_sync):
        assert disabled_sync.get_gates("s", "dev") is None

    def test_log_action(self, disabled_sync):
        assert disabled_sync.log_action("register", "s") is True

    def test_health_check(self, disabled_sync):
        assert disabled_sync.health_check() is True


# ─────────────────────────────────────────────────────────────────────────── #
# enabled + adapter → sucesso                                                  #
# ─────────────────────────────────────────────────────────────────────────── #
class TestEnabledSuccess:
    def test_pipeline_registered_calls_adapter(self, sync):
        ok = sync.sync_pipeline_registered(
            {"service": "svc", "repo": "org/svc", "base_branch": "develop"}
        )
        assert ok is True
        sync.adapter.sync_to_postgres.assert_called_once()
        table, data = sync.adapter.sync_to_postgres.call_args.args
        assert table == "pipelines"
        assert data["service"] == "svc"

    def test_env_updated_queries(self, sync):
        assert sync.sync_pipeline_env_updated("svc", "homol", version="v1") is True
        sync.adapter.query_postgres.assert_called_once()
        sql, params = sync.adapter.query_postgres.call_args.args
        assert "UPDATE pipelines" in sql
        assert params == ("homol", "v1", "svc")

    def test_blocked_queries(self, sync):
        assert sync.sync_pipeline_blocked("svc", "r", "a") is True
        sql, params = sync.adapter.query_postgres.call_args.args
        assert "blocked = true" in sql
        assert params == ("r", "a", "svc")

    def test_promotion_created(self, sync):
        ok = sync.sync_promotion_created(
            {"service": "svc", "from_env": "dev", "to_env": "homol", "promoted_by": "u"}
        )
        assert ok is True
        table, data = sync.adapter.sync_to_postgres.call_args.args
        assert table == "promotions"
        assert data["to_env"] == "homol"

    def test_promotion_completed(self, sync):
        assert (
            sync.sync_promotion_completed(9, "success", completed_at="2026-01-01T00:00:00Z") is True
        )
        sql, params = sync.adapter.query_postgres.call_args.args
        assert params == ("success", "2026-01-01T00:00:00Z", 9)

    def test_promotion_completed_default_timestamp(self, sync):
        assert sync.sync_promotion_completed(9, "success") is True
        _, params = sync.adapter.query_postgres.call_args.args
        assert params[2] == 9
        assert params[1].endswith("Z")

    def test_promotion_approved(self, sync):
        assert sync.sync_promotion_approved(9, "bob", "2026-01-01T00:00:00Z") is True
        sql, params = sync.adapter.query_postgres.call_args.args
        assert "status = 'approved'" in sql
        assert params == ("bob", "2026-01-01T00:00:00Z", 9)

    def test_gate_evaluated(self, sync):
        assert sync.sync_gate_evaluated("svc", "dev", "qa_tests", True, details={"x": 1}) is True
        table, data = sync.adapter.sync_to_postgres.call_args.args
        assert table == "gates"
        assert data["environment"] == "dev"
        assert data["passed"] is True

    def test_get_pipeline_found(self, sync):
        sync.adapter.query_postgres.return_value = [{"service": "svc"}]
        assert sync.get_pipeline("svc") == {"service": "svc"}

    def test_get_pipeline_empty(self, sync):
        sync.adapter.query_postgres.return_value = []
        assert sync.get_pipeline("svc") is None

    def test_list_promotions_with_filters(self, sync):
        sync.adapter.query_postgres.return_value = [{"id": 1}]
        result = sync.list_promotions(service="svc", status="pending")
        assert result == [{"id": 1}]
        sql, params = sync.adapter.query_postgres.call_args.args
        assert "AND service = %s" in sql
        assert "AND status = %s" in sql
        assert params == ("svc", "pending")

    def test_list_promotions_no_filters(self, sync):
        sync.adapter.query_postgres.return_value = []
        sync.list_promotions()
        _, params = sync.adapter.query_postgres.call_args.args
        assert params is None

    def test_get_gates(self, sync):
        sync.adapter.query_postgres.return_value = [{"gate_type": "qa_tests"}]
        assert sync.get_gates("svc", "dev") == [{"gate_type": "qa_tests"}]

    def test_log_action(self, sync):
        assert sync.log_action("register", "svc", actor_id=1, details={"k": "v"}) is True
        sync.adapter.audit_log.assert_called_once()

    def test_health_check_true(self, sync):
        sync.adapter.health_check.return_value = True
        assert sync.health_check() is True


# ─────────────────────────────────────────────────────────────────────────── #
# enabled + adapter levanta exceção → False                                    #
# ─────────────────────────────────────────────────────────────────────────── #
class TestExceptionsReturnFalse:
    @pytest.fixture
    def boom(self, sync) -> PipelinePostgresSync:
        def _raise(*a: Any, **k: Any):
            raise RuntimeError("db error")

        sync.adapter.sync_to_postgres.side_effect = _raise
        sync.adapter.query_postgres.side_effect = _raise
        sync.adapter.audit_log.side_effect = _raise
        sync.adapter.health_check.side_effect = _raise
        return sync

    def test_pipeline_registered(self, boom):
        assert boom.sync_pipeline_registered({"service": "s", "repo": "r"}) is False

    def test_env_updated(self, boom):
        assert boom.sync_pipeline_env_updated("s", "homol") is False

    def test_blocked(self, boom):
        assert boom.sync_pipeline_blocked("s", "r", "a") is False

    def test_promotion_created(self, boom):
        assert (
            boom.sync_promotion_created({"service": "s", "from_env": "d", "to_env": "h"}) is False
        )

    def test_promotion_completed(self, boom):
        assert boom.sync_promotion_completed(1, "s") is False

    def test_promotion_approved(self, boom):
        assert boom.sync_promotion_approved(1, "a", "t") is False

    def test_gate_evaluated(self, boom):
        assert boom.sync_gate_evaluated("s", "dev", "qa_tests", True) is False

    def test_get_pipeline(self, boom):
        assert boom.get_pipeline("s") is None

    def test_list_promotions(self, boom):
        assert boom.list_promotions() is None

    def test_get_gates(self, boom):
        assert boom.get_gates("s", "dev") is None

    def test_log_action(self, boom):
        assert boom.log_action("register", "s") is False

    def test_health_check(self, boom):
        assert boom.health_check() is False
