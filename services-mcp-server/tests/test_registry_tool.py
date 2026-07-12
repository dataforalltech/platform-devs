"""Tools CRUD do registry contra MySQL real (§16 / FID-02): register/get/list/update/
unregister, incluindo os caminhos de validação (retornam antes do store)."""

from __future__ import annotations

import pytest

from src.tools.registry_tool import (
    get_service,
    list_services,
    register_service,
    unregister_service,
    update_service,
)

from .conftest import requires_mysql

pytestmark = [pytest.mark.integration, requires_mysql]


# ── register_service ──────────────────────────────────────────────────────────
async def test_register_creates_and_updates(store_a):
    created = await register_service(
        store_a,
        name="svc",
        port=8080,
        host="127.0.0.1",
        type="docker",
        environment="local",
        tags=["web"],
        metadata={"image": "nginx"},
        runtime="uvicorn",
        deploy_mode="asgi",
        os_name="linux",
    )
    assert created["action"] == "created"
    assert created["service"]["name"] == "svc"
    assert created["service"]["port"] == 8080
    assert created["service"]["tags"] == ["web"]
    assert created["service"]["runtime"] == "uvicorn"

    updated = await register_service(store_a, name="svc", port=8080, status="running")
    assert updated["action"] == "updated"
    assert updated["service"]["status"] == "running"


async def test_register_validation_errors(store_a):
    assert (await register_service(store_a, name="  ", port=8080))["error"] == "ValidationError"
    assert (await register_service(store_a, name="svc", port=0))["error"] == "ValidationError"
    assert (await register_service(store_a, name="svc", port=70000))["error"] == "ValidationError"
    bad_type = await register_service(store_a, name="svc", port=8080, type="banana")
    assert bad_type["error"] == "ValidationError"
    bad_env = await register_service(store_a, name="svc", port=8080, environment="space")
    assert bad_env["error"] == "ValidationError"


# ── get_service ───────────────────────────────────────────────────────────────
async def test_get_service_found_and_missing(store_a):
    await register_service(store_a, name="svc", port=8080)
    found = await get_service(store_a, name="svc")
    assert found["found"] is True
    assert found["service"]["name"] == "svc"

    missing = await get_service(store_a, name="ghost")
    assert missing == {"found": False, "name": "ghost"}


# ── list_services ─────────────────────────────────────────────────────────────
async def test_list_services_filters(store_a):
    await register_service(store_a, name="a", port=1, type="docker", environment="local", tags=["web"])
    await register_service(store_a, name="b", port=2, type="process", environment="hml")

    result = await list_services(store_a)
    assert result["total"] == 2

    only_docker = await list_services(store_a, type="docker")
    assert only_docker["total"] == 1
    assert only_docker["services"][0]["name"] == "a"

    only_hml = await list_services(store_a, environment="hml")
    assert {s["name"] for s in only_hml["services"]} == {"b"}

    tagged = await list_services(store_a, tag="web")
    assert {s["name"] for s in tagged["services"]} == {"a"}


# ── update_service ────────────────────────────────────────────────────────────
async def test_update_service_partial(store_a):
    await register_service(store_a, name="svc", port=8080, type="docker")
    result = await update_service(store_a, name="svc", status="running", port=9090)
    assert result["updated_fields"] == ["port", "status"]
    assert result["service"]["status"] == "running"
    assert result["service"]["port"] == 9090
    assert result["service"]["type"] == "docker"  # preservado


async def test_update_service_no_fields(store_a):
    await register_service(store_a, name="svc", port=8080)
    result = await update_service(store_a, name="svc")
    assert result["error"] == "ValidationError"


async def test_update_service_not_found(store_a):
    result = await update_service(store_a, name="ghost", status="running")
    assert result["error"] == "NotFound"


async def test_update_service_field_validation(store_a):
    await register_service(store_a, name="svc", port=8080)
    assert (await update_service(store_a, name="svc", port=0))["error"] == "ValidationError"
    assert (await update_service(store_a, name="svc", type="banana"))["error"] == "ValidationError"
    assert (await update_service(store_a, name="svc", environment="x"))["error"] == "ValidationError"
    assert (await update_service(store_a, name="svc", status="x"))["error"] == "ValidationError"


# ── unregister_service ────────────────────────────────────────────────────────
async def test_unregister_service(store_a):
    await register_service(store_a, name="svc", port=8080)
    assert (await unregister_service(store_a, name="svc"))["deleted"] is True
    assert (await get_service(store_a, name="svc"))["found"] is False
    assert (await unregister_service(store_a, name="svc"))["deleted"] is False
