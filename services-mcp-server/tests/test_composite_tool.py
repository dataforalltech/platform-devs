"""Testes das tools compostas."""

from __future__ import annotations

from unittest.mock import patch

from src.tools.composite_tool import list_environments, service_status

from .conftest import make_service

# ── service_status ────────────────────────────────────────────────────────── #


def test_service_status_healthy(store):
    make_service(store, name="api-gateway", port=8080)

    health_result = {
        "name": "api-gateway",
        "healthy": True,
        "status_code": 200,
        "url_checked": "http://localhost:8080/health",
        "response_ms": 12.0,
    }

    with patch("src.tools.composite_tool.check_health", return_value=health_result):
        result = service_status(store, name="api-gateway", timeout=2.0)

    assert result["found"] is True
    assert result["overall_status"] == "healthy"
    assert result["name"] == "api-gateway"
    assert "service" in result
    assert result["health"]["healthy"] is True


def test_service_status_unhealthy(store):
    make_service(store, name="api-gateway", port=8080)

    health_result = {
        "name": "api-gateway",
        "healthy": False,
        "status_code": 503,
        "url_checked": "http://localhost:8080/health",
        "response_ms": 5.0,
    }

    with patch("src.tools.composite_tool.check_health", return_value=health_result):
        result = service_status(store, name="api-gateway", timeout=2.0)

    assert result["found"] is True
    assert result["overall_status"] == "unhealthy"


def test_service_status_not_found(store):
    result = service_status(store, name="ghost", timeout=2.0)
    assert result["found"] is False
    assert result["overall_status"] == "unknown"
    assert result["name"] == "ghost"


# ── list_environments ─────────────────────────────────────────────────────── #


def test_list_environments_empty(store):
    result = list_environments(store)
    assert result["total_services"] == 0
    assert result["total_environments"] == 0
    assert result["environments"] == []


def test_list_environments_with_services(store):
    make_service(store, name="svc-a", port=8001, environment="local", status="running")
    make_service(store, name="svc-b", port=8002, environment="local", status="stopped")
    make_service(store, name="svc-c", port=8003, environment="dev", status="running")

    result = list_environments(store)

    assert result["total_services"] == 3
    assert result["total_environments"] == 2

    env_map = {e["environment"]: e for e in result["environments"]}

    assert "local" in env_map
    assert env_map["local"]["total"] == 2
    assert env_map["local"]["running"] == 1
    assert env_map["local"]["stopped"] == 1

    assert "dev" in env_map
    assert env_map["dev"]["total"] == 1
    assert env_map["dev"]["running"] == 1


def test_list_environments_sorted(store):
    make_service(store, name="svc-z", port=8001, environment="prod")
    make_service(store, name="svc-a", port=8002, environment="dev")
    make_service(store, name="svc-b", port=8003, environment="local")

    result = list_environments(store)
    envs = [e["environment"] for e in result["environments"]]
    assert envs == sorted(envs)
