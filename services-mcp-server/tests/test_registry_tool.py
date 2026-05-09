"""Testes das tools CRUD de registro de serviços."""

from __future__ import annotations

from src.tools.registry_tool import (
    get_service,
    list_services,
    register_service,
    unregister_service,
    update_service,
)

from .conftest import make_service

# ── register_service ──────────────────────────────────────────────────────── #


def test_register_creates_new_service(store):
    result = register_service(store, name="svc-a", port=8001)
    assert result["action"] == "created"
    assert result["name"] == "svc-a"
    svc = result["service"]
    assert svc["port"] == 8001
    assert svc["type"] == "unknown"
    assert svc["environment"] == "local"


def test_register_updates_existing(store):
    register_service(store, name="svc-a", port=8001)
    result = register_service(store, name="svc-a", port=8002)
    assert result["action"] == "updated"
    assert result["service"]["port"] == 8002


def test_register_invalid_port_returns_error(store):
    result = register_service(store, name="svc-a", port=0)
    assert result["error"] == "ValidationError"
    assert "port" in result["details"]


def test_register_invalid_port_too_large(store):
    result = register_service(store, name="svc-a", port=99999)
    assert result["error"] == "ValidationError"


def test_register_invalid_type_returns_error(store):
    result = register_service(store, name="svc-a", port=8080, type="kubernetes")
    assert result["error"] == "ValidationError"
    assert "type" in result["details"]


def test_register_invalid_environment_returns_error(store):
    result = register_service(store, name="svc-a", port=8080, environment="staging")
    assert result["error"] == "ValidationError"
    assert "environment" in result["details"]


def test_register_empty_name_returns_error(store):
    result = register_service(store, name="", port=8080)
    assert result["error"] == "ValidationError"
    assert "name" in result["details"]


def test_register_preserves_tags(store):
    result = register_service(store, name="svc-a", port=8080, tags=["api", "core"])
    assert result["service"]["tags"] == ["api", "core"]


# ── get_service ───────────────────────────────────────────────────────────── #


def test_get_existing_service(store):
    make_service(store, name="api-gateway", port=8080)
    result = get_service(store, name="api-gateway")
    assert result["found"] is True
    assert result["service"]["name"] == "api-gateway"
    assert result["service"]["port"] == 8080


def test_get_nonexistent_service(store):
    result = get_service(store, name="nonexistent")
    assert result["found"] is False
    assert result["name"] == "nonexistent"


# ── list_services ─────────────────────────────────────────────────────────── #


def test_list_all_services(store):
    make_service(store, name="svc-a", port=8001)
    make_service(store, name="svc-b", port=8002)
    result = list_services(store)
    assert result["total"] == 2
    names = [s["name"] for s in result["services"]]
    assert "svc-a" in names
    assert "svc-b" in names


def test_list_filtered_by_environment(store):
    make_service(store, name="svc-local", port=8001, environment="local")
    make_service(store, name="svc-dev", port=8002, environment="dev")
    result = list_services(store, environment="dev")
    assert result["total"] == 1
    assert result["services"][0]["name"] == "svc-dev"


def test_list_filtered_by_type(store):
    make_service(store, name="svc-docker", port=8001, type_="docker")
    make_service(store, name="svc-remote", port=8002, type_="remote")
    result = list_services(store, type="docker")
    assert result["total"] == 1
    assert result["services"][0]["name"] == "svc-docker"


def test_list_filtered_by_tag(store):
    make_service(store, name="svc-tagged", port=8001, tags=["api"])
    make_service(store, name="svc-other", port=8002, tags=["worker"])
    result = list_services(store, tag="api")
    assert result["total"] == 1
    assert result["services"][0]["name"] == "svc-tagged"


def test_list_empty_returns_zero(store):
    result = list_services(store)
    assert result["total"] == 0
    assert result["services"] == []


# ── update_service ────────────────────────────────────────────────────────── #


def test_update_service_fields(store):
    make_service(store, name="svc-a", port=8001)
    result = update_service(store, name="svc-a", port=9001, status="stopped")
    assert "port" in result["updated_fields"]
    assert "status" in result["updated_fields"]
    assert result["service"]["port"] == 9001
    assert result["service"]["status"] == "stopped"


def test_update_nonexistent_returns_error(store):
    result = update_service(store, name="ghost", port=9000)
    assert result["error"] == "NotFound"
    assert result["name"] == "ghost"


def test_update_no_fields_returns_error(store):
    make_service(store, name="svc-a", port=8001)
    result = update_service(store, name="svc-a")
    assert result["error"] == "ValidationError"


def test_update_invalid_port(store):
    make_service(store, name="svc-a", port=8001)
    result = update_service(store, name="svc-a", port=-1)
    assert result["error"] == "ValidationError"


# ── unregister_service ────────────────────────────────────────────────────── #


def test_unregister_existing(store):
    make_service(store, name="svc-a", port=8001)
    result = unregister_service(store, name="svc-a")
    assert result["deleted"] is True
    assert result["name"] == "svc-a"
    # confirm removed
    assert get_service(store, name="svc-a")["found"] is False


def test_unregister_nonexistent(store):
    result = unregister_service(store, name="ghost")
    assert result["deleted"] is False
    assert result["name"] == "ghost"
