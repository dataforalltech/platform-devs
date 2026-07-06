"""Testes da camada HTTP endpoints (PostgreSQL sync layer).

Herméticos: postgres_sync é um MagicMock — nenhuma I/O de banco.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from src.server.http_endpoints import ServicesHTTPEndpoints


def _endpoints() -> tuple[ServicesHTTPEndpoints, MagicMock]:
    sync = MagicMock()
    return ServicesHTTPEndpoints(sync), sync


# ── GET /services ─────────────────────────────────────────────────────────── #


def test_get_services_ok():
    ep, sync = _endpoints()
    sync.list_services.return_value = [
        {"name": "a", "type": "docker"},
        {"name": "b", "type": "api"},
    ]
    result = ep.get_services()
    assert result["status"] == 200
    assert result["total"] == 2


def test_get_services_type_filter():
    ep, sync = _endpoints()
    sync.list_services.return_value = [
        {"name": "a", "type": "docker"},
        {"name": "b", "type": "api"},
    ]
    result = ep.get_services(service_type="docker")
    assert result["total"] == 1


def test_get_services_db_error():
    ep, sync = _endpoints()
    sync.list_services.return_value = None
    result = ep.get_services()
    assert result["status"] == 500


def test_get_services_exception():
    ep, sync = _endpoints()
    sync.list_services.side_effect = RuntimeError("boom")
    result = ep.get_services()
    assert result["status"] == 500
    assert result["error"] == "internal_error"


# ── GET /services/{name} ──────────────────────────────────────────────────── #


def test_get_service_found():
    ep, sync = _endpoints()
    sync.get_service.return_value = {"name": "a", "port": 1}
    result = ep.get_service("a")
    assert result["status"] == 200
    assert result["name"] == "a"


def test_get_service_not_found():
    ep, sync = _endpoints()
    sync.get_service.return_value = None
    result = ep.get_service("ghost")
    assert result["status"] == 404


# ── POST /services ────────────────────────────────────────────────────────── #


def test_post_services_created():
    ep, sync = _endpoints()
    sync.get_service.return_value = None
    result = ep.post_services(name="x", service_type="docker", host="h", port=1)
    assert result["status"] == 201
    assert result["service_status"] == "unknown"
    sync.sync_service_registered.assert_called_once()
    sync.log_action.assert_called_once()


def test_post_services_conflict():
    ep, sync = _endpoints()
    sync.get_service.return_value = {"name": "x"}
    result = ep.post_services(name="x", service_type="docker", host="h", port=1)
    assert result["status"] == 409


def test_post_services_exception():
    ep, sync = _endpoints()
    sync.get_service.side_effect = RuntimeError("boom")
    result = ep.post_services(name="x", service_type="docker", host="h", port=1)
    assert result["status"] == 500


# ── PATCH /services/{name} ────────────────────────────────────────────────── #


def test_patch_service_ok():
    ep, sync = _endpoints()
    sync.get_service.return_value = {"name": "x"}
    result = ep.patch_service("x", description="new")
    assert result["status"] == 200
    assert result["updated"] is True


def test_patch_service_not_found():
    ep, sync = _endpoints()
    sync.get_service.return_value = None
    result = ep.patch_service("ghost", description="new")
    assert result["status"] == 404


# ── GET /services/health ──────────────────────────────────────────────────── #


def test_get_services_health_summary():
    ep, sync = _endpoints()
    sync.list_services.return_value = [
        {"name": "a", "status": "healthy"},
        {"name": "b", "status": "healthy"},
        {"name": "c", "status": "unknown"},
    ]
    sync.list_unhealthy_services.return_value = [{"name": "d", "status": "unhealthy"}]
    result = ep.get_services_health()
    assert result["status"] == 200
    assert result["healthy"] == 2
    assert result["unhealthy"] == 1
    assert result["unknown"] == 1
    assert result["total"] == 3


def test_get_services_health_db_error():
    ep, sync = _endpoints()
    sync.list_services.return_value = None
    result = ep.get_services_health()
    assert result["status"] == 500


# ── POST /services/{name}/health-check ────────────────────────────────────── #


def test_post_health_check_ok():
    ep, sync = _endpoints()
    sync.get_service.return_value = {"name": "x"}
    result = ep.post_service_health_check("x", status="healthy", response_time_ms=12.5)
    assert result["status"] == 200
    assert result["service_status"] == "healthy"
    sync.sync_health_check_result.assert_called_once()


def test_post_health_check_not_found():
    ep, sync = _endpoints()
    sync.get_service.return_value = None
    result = ep.post_service_health_check("ghost", status="healthy")
    assert result["status"] == 404


# ── DELETE /services/{name} ───────────────────────────────────────────────── #


def test_delete_service_ok():
    ep, sync = _endpoints()
    sync.get_service.return_value = {"name": "x"}
    result = ep.delete_service("x")
    assert result["status"] == 200
    assert result["deleted"] is True
    sync.sync_service_removed.assert_called_once()


def test_delete_service_not_found():
    ep, sync = _endpoints()
    sync.get_service.return_value = None
    result = ep.delete_service("ghost")
    assert result["status"] == 404
