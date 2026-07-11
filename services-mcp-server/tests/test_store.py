"""Store canônico contra MySQL real (§16 / FID-02): CRUD do registry, defaults de
criação, upsert parcial, soft-delete + reativação, filtros e ISOLAMENTO por tenant
(banco-por-tenant)."""

from __future__ import annotations

import pytest

from src.models.service import service_record

from .conftest import requires_mysql

pytestmark = [pytest.mark.integration, requires_mysql]


# ── Create / defaults ─────────────────────────────────────────────────────────
async def test_upsert_creates_then_updates(store_a):
    created = await store_a.upsert(
        "svc-a",
        {
            "host": "localhost",
            "port": 8080,
            "type": "docker",
            "environment": "local",
            "status": "running",
            "tags": ["web", "api"],
            "metadata": {"image": "nginx:latest"},
        },
    )
    assert created["action"] == "created"
    rec = service_record(created["row"])
    assert rec["name"] == "svc-a"
    assert rec["port"] == 8080
    assert rec["type"] == "docker"
    assert rec["status"] == "running"
    assert rec["tags"] == ["web", "api"]  # JSON parseado
    assert rec["metadata"] == {"image": "nginx:latest"}

    # Update parcial: só troca o status; port/type preservados (não resetados).
    updated = await store_a.upsert("svc-a", {"status": "stopped"})
    assert updated["action"] == "updated"
    rec2 = service_record(updated["row"])
    assert rec2["status"] == "stopped"
    assert rec2["port"] == 8080
    assert rec2["type"] == "docker"


async def test_create_defaults_applied(store_a):
    # Só port informado -> os defaults históricos são carimbados no create.
    created = await store_a.upsert("minimal", {"port": 9000})
    rec = service_record(created["row"])
    assert rec["host"] == "localhost"
    assert rec["type"] == "unknown"
    assert rec["status"] == "unknown"
    assert rec["environment"] == "local"
    assert rec["health_path"] == "/health"
    assert rec["runtime"] == "unknown"
    assert rec["tags"] == []
    assert rec["metadata"] == {}
    assert rec["registered_at"] is not None


async def test_metadata_accepts_json_string(store_a):
    # O gateway_tool passa metadata já serializado (str JSON) — deve ser preservado.
    created = await store_a.upsert("svc", {"port": 7000, "metadata": '{"host_port": 9094}'})
    rec = service_record(created["row"])
    assert rec["metadata"] == {"host_port": 9094}


# ── Reads / filtros ───────────────────────────────────────────────────────────
async def test_get_none_when_absent(store_a):
    assert await store_a.get("nao-existe") is None


async def test_list_all_filters(store_a):
    await store_a.upsert("a", {"port": 1, "type": "docker", "environment": "local", "status": "running"})
    await store_a.upsert("b", {"port": 2, "type": "process", "environment": "hml", "status": "stopped"})

    names = [service_record(r)["name"] for r in await store_a.list_all()]
    assert names == ["a", "b"]  # ordenado por name

    assert {service_record(r)["name"] for r in await store_a.list_all(environment="hml")} == {"b"}
    assert {service_record(r)["name"] for r in await store_a.list_all(type_="docker")} == {"a"}
    assert {service_record(r)["name"] for r in await store_a.list_all(status="stopped")} == {"b"}


async def test_list_all_tag_filter(store_a):
    await store_a.upsert("infra", {"port": 3306, "tags": ["infra", "database"]})
    await store_a.upsert("app", {"port": 8000, "tags": ["web"]})

    assert {service_record(r)["name"] for r in await store_a.list_all(tag="database")} == {"infra"}
    assert await store_a.list_all(tag="inexistente") == []


async def test_list_all_runtime_deploy_mode_filter(store_a):
    await store_a.upsert("u", {"port": 1, "runtime": "uvicorn", "deploy_mode": "asgi"})
    await store_a.upsert("n", {"port": 2, "runtime": "node", "deploy_mode": "node"})

    assert {service_record(r)["name"] for r in await store_a.list_all(runtime="uvicorn")} == {"u"}
    assert {service_record(r)["name"] for r in await store_a.list_all(deploy_mode="node")} == {"n"}


# ── update_check ──────────────────────────────────────────────────────────────
async def test_update_check(store_a):
    await store_a.upsert("svc", {"port": 8080})
    await store_a.update_check("svc", True)
    rec = service_record(await store_a.get("svc"))
    assert rec["last_check_ok"] is True
    assert rec["last_check_at"] is not None

    await store_a.update_check("svc", False)
    assert service_record(await store_a.get("svc"))["last_check_ok"] is False


# ── Delete (soft-delete) + reativação ─────────────────────────────────────────
async def test_delete_soft_and_reactivate(store_a):
    await store_a.upsert("svc", {"port": 8080})
    assert await store_a.get("svc") is not None

    assert await store_a.delete("svc") is True
    assert await store_a.get("svc") is None
    assert await store_a.list_all() == []

    # re-registrar reativa a linha soft-deletada (mesma chave única, sem violar UNIQUE)
    reactivated = await store_a.upsert("svc", {"port": 8081, "status": "running"})
    assert reactivated["action"] == "created"
    rec = service_record(reactivated["row"])
    assert rec["port"] == 8081
    assert len(await store_a.list_all()) == 1

    # delete de serviço inexistente -> False
    assert await store_a.delete("nao-existe") is False


# ── Isolamento por tenant (banco-por-tenant, dual-db) ─────────────────────────
async def test_tenant_isolation(store_a, store_b):
    await store_a.upsert("only-in-a", {"port": 8080})
    assert len(await store_a.list_all()) == 1
    # o tenant B tem SEU PRÓPRIO banco → não enxerga dados do A
    assert await store_b.list_all() == []
    assert await store_b.get("only-in-a") is None
