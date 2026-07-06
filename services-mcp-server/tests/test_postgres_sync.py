"""Testes da camada ServicesPostgresSync (sync layer legado).

Herméticos: o adapter PostgreSQL é um MagicMock — nenhuma conexão real.
Também cobre o caminho 'disabled' (sem adapter), em que todo método é no-op.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.db.postgres_sync import ServicesPostgresSync


@pytest.fixture
def disabled_sync() -> ServicesPostgresSync:
    # enabled=False → nunca tenta importar o adapter nem conectar
    return ServicesPostgresSync(postgres_config={}, enabled=False)


@pytest.fixture
def enabled_sync() -> ServicesPostgresSync:
    s = ServicesPostgresSync(postgres_config={}, enabled=False)
    # Injeta um adapter mock e habilita, exercitando os caminhos "enabled"
    s.adapter = MagicMock()
    s.enabled = True
    return s


# ── caminho disabled (no-op) ──────────────────────────────────────────────── #


def test_init_import_failure_disables():
    # enabled=True tenta importar lib.mcp_postgres_adapter (inexistente) → desabilita
    s = ServicesPostgresSync(postgres_config={}, enabled=True)
    assert s.enabled is False
    assert s.adapter is None


def test_disabled_methods_are_noops(disabled_sync):
    assert disabled_sync.sync_service_registered({"name": "x"}) is True
    assert disabled_sync.sync_service_updated("x", {"description": "d"}) is True
    assert disabled_sync.sync_health_check_result("x", "healthy") is True
    assert disabled_sync.sync_service_removed("x") is True
    assert disabled_sync.list_services() is None
    assert disabled_sync.get_service("x") is None
    assert disabled_sync.list_unhealthy_services() is None
    assert disabled_sync.log_action("register", "x") is True
    assert disabled_sync.health_check() is True
    disabled_sync.close()  # sem adapter, no-op


# ── caminho enabled (adapter mockado) ─────────────────────────────────────── #


def test_sync_service_registered(enabled_sync):
    ok = enabled_sync.sync_service_registered({"name": "x", "type": "docker", "port": 1})
    assert ok is True
    enabled_sync.adapter.sync_to_postgres.assert_called_once()


def test_sync_service_registered_error(enabled_sync):
    enabled_sync.adapter.sync_to_postgres.side_effect = RuntimeError("boom")
    assert enabled_sync.sync_service_registered({"name": "x"}) is False


def test_sync_service_updated_with_fields(enabled_sync):
    ok = enabled_sync.sync_service_updated("x", {"description": "d", "environment": "dev"})
    assert ok is True
    enabled_sync.adapter.query_postgres.assert_called_once()


def test_sync_service_updated_no_fields(enabled_sync):
    # Nenhum campo mapeável → retorna True sem chamar o adapter
    assert enabled_sync.sync_service_updated("x", {"irrelevant": 1}) is True
    enabled_sync.adapter.query_postgres.assert_not_called()


def test_sync_health_check_result(enabled_sync):
    assert enabled_sync.sync_health_check_result("x", "healthy", 12.0) is True
    enabled_sync.adapter.query_postgres.assert_called_once()


def test_sync_service_removed(enabled_sync):
    assert enabled_sync.sync_service_removed("x") is True
    enabled_sync.adapter.query_postgres.assert_called_once()


def test_list_services_with_filters(enabled_sync):
    enabled_sync.adapter.query_postgres.return_value = [{"name": "a"}]
    result = enabled_sync.list_services(environment="dev", status="healthy")
    assert result == [{"name": "a"}]


def test_list_services_error(enabled_sync):
    enabled_sync.adapter.query_postgres.side_effect = RuntimeError("boom")
    assert enabled_sync.list_services() is None


def test_get_service_found(enabled_sync):
    enabled_sync.adapter.query_postgres.return_value = [{"name": "a", "port": 1}]
    result = enabled_sync.get_service("a")
    assert result["name"] == "a"


def test_get_service_none(enabled_sync):
    enabled_sync.adapter.query_postgres.return_value = []
    assert enabled_sync.get_service("a") is None


def test_list_unhealthy(enabled_sync):
    enabled_sync.adapter.query_postgres.return_value = [{"name": "bad"}]
    assert enabled_sync.list_unhealthy_services() == [{"name": "bad"}]


def test_log_action(enabled_sync):
    assert enabled_sync.log_action("register", "x", actor_id=1, details={"k": "v"}) is True
    enabled_sync.adapter.audit_log.assert_called_once()


def test_log_action_error(enabled_sync):
    enabled_sync.adapter.audit_log.side_effect = RuntimeError("boom")
    assert enabled_sync.log_action("register", "x") is False


def test_health_check(enabled_sync):
    enabled_sync.adapter.health_check.return_value = True
    assert enabled_sync.health_check() is True


def test_health_check_error(enabled_sync):
    enabled_sync.adapter.health_check.side_effect = RuntimeError("boom")
    assert enabled_sync.health_check() is False


def test_close_calls_adapter(enabled_sync):
    enabled_sync.close()
    enabled_sync.adapter.close.assert_called_once()
