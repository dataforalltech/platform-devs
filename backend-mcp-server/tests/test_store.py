"""Store canônico contra MySQL real (§16 / FID-02): CRUD das 5 entidades, upsert de
chaves naturais (contrato por endpoint+method, política por resource), soft-delete e
ISOLAMENTO por tenant."""

from __future__ import annotations

import pytest

from .conftest import requires_mysql

pytestmark = [pytest.mark.integration, requires_mysql]


# ── API Contracts (upsert por endpoint+method) ────────────────────────────────
async def test_api_contract_upsert_by_endpoint_method(store_a):
    first = await store_a.save_api_contract(
        endpoint="/users",
        method="POST",
        description="cria usuário",
        request_schema={"name": "str"},
        response_schema={"id": "int"},
        status_codes=[201, 400],
        status="draft",
    )
    assert first["endpoint"] == "/users" and first["method"] == "POST"
    assert first["request_schema"] == {"name": "str"}  # JSON round-trip
    assert first["status_codes"] == [201, 400]

    # mesmo endpoint+method → upsert (não duplica), sobrescreve
    second = await store_a.save_api_contract(
        endpoint="/users", method="POST", description="v2", status="approved"
    )
    assert second["description"] == "v2" and second["status"] == "approved"

    # endpoint igual, method diferente → NOVA linha (chave composta)
    await store_a.save_api_contract(endpoint="/users", method="GET", status="draft")

    contracts = await store_a.list_api_contracts(endpoint="/users")
    assert len(contracts) == 2  # POST (upsert) + GET
    assert len(await store_a.list_api_contracts(method="POST")) == 1

    got = await store_a.get_api_contract("/users", "POST")
    assert got is not None and got["description"] == "v2"
    assert await store_a.get_api_contract("/users", "PUT") is None

    assert await store_a.delete_api_contract("/users", "POST") == 1
    assert await store_a.get_api_contract("/users", "POST") is None
    assert len(await store_a.list_api_contracts()) == 1  # sobra o GET


# ── Database Schemas (histórico, chave surrogate id) ───────────────────────────
async def test_database_schema_crud(store_a):
    saved = await store_a.save_database_schema(
        entity="orders",
        database_name="postgres",
        attributes=[{"name": "id", "type": "int"}],
        relationships=[{"to": "users"}],
        indexes=["idx_orders_id"],
        constraints=["PRIMARY KEY"],
        status="draft",
    )
    assert saved["id"] > 0
    assert saved["attributes"] == [{"name": "id", "type": "int"}]
    assert saved["relationships"] == [{"to": "users"}]
    assert saved["indexes"] == ["idx_orders_id"]

    got = await store_a.get_database_schema(saved["id"])
    assert got is not None and got["database_name"] == "postgres"

    updated = await store_a.update_database_schema(saved["id"], database_name="mysql", status="approved")
    assert updated is not None and updated["database_name"] == "mysql" and updated["status"] == "approved"

    assert {s["id"] for s in await store_a.list_database_schemas(entity="orders")} == {saved["id"]}
    assert await store_a.list_database_schemas(database_name="mysql") != []

    assert await store_a.delete_database_schema(saved["id"]) == 1
    assert await store_a.get_database_schema(saved["id"]) is None
    assert await store_a.list_database_schemas() == []


async def test_database_schema_get_missing_returns_none(store_a):
    assert await store_a.get_database_schema(999999) is None
    assert await store_a.update_database_schema(999999, status="x") is None
    assert await store_a.delete_database_schema(999999) == 0


# ── Auth Policies (upsert por resource) ────────────────────────────────────────
async def test_auth_policy_upsert_by_resource(store_a):
    first = await store_a.save_auth_policy(
        resource="orders",
        auth_type="jwt",
        roles=["admin", "user"],
        data_sensitivity="confidential",
        rules={"mfa": True},
        status="active",
    )
    assert first["resource"] == "orders"
    assert first["roles"] == ["admin", "user"]
    assert first["rules"] == {"mfa": True}

    # mesmo resource → upsert (não duplica), sobrescreve
    second = await store_a.save_auth_policy(resource="orders", auth_type="oauth", status="blocking")
    assert second["auth_type"] == "oauth" and second["status"] == "blocking"

    policies = await store_a.list_auth_policies()
    assert len(policies) == 1  # ON DUPLICATE KEY: uma linha só
    assert await store_a.list_auth_policies(auth_type="oauth") != []

    got = await store_a.get_auth_policy("orders")
    assert got is not None and got["auth_type"] == "oauth"
    assert await store_a.get_auth_policy("inexistente") is None

    assert await store_a.delete_auth_policy("orders") == 1
    assert await store_a.get_auth_policy("orders") is None


# ── Backend Artifacts (histórico append-only) ──────────────────────────────────
async def test_artifact_history_append_only(store_a):
    a1 = await store_a.save_artifact(
        kind="router", target="users", content="router = APIRouter()", framework="fastapi"
    )
    a2 = await store_a.save_artifact(
        kind="migration", target="orders", content="ALTER TABLE ...", meta={"reversible": True}
    )
    assert a1["id"] != a2["id"]
    assert a2["meta"] == {"reversible": True}
    assert a2["content"] == "ALTER TABLE ..."  # texto livre, não JSON

    assert {a["id"] for a in await store_a.list_artifacts(kind="router")} == {a1["id"]}
    assert {a["id"] for a in await store_a.list_artifacts(target="orders")} == {a2["id"]}
    assert len(await store_a.list_artifacts()) == 2

    got = await store_a.get_artifact(a1["id"])
    assert got is not None and got["kind"] == "router"

    assert await store_a.delete_artifact(a1["id"]) == 1
    assert await store_a.get_artifact(a1["id"]) is None
    assert len(await store_a.list_artifacts()) == 1


# ── Code Reviews (histórico append-only) ───────────────────────────────────────
async def test_code_review_crud(store_a):
    saved = await store_a.save_code_review(
        target="app/api/users.py",
        language="python",
        focus=["security", "performance"],
        findings=[{"line": 10, "issue": "sql injection"}],
        security_score=6.5,
        performance_score=8.0,
        summary="corrigir input não sanitizado",
        status="open",
    )
    assert saved["id"] > 0
    assert saved["focus"] == ["security", "performance"]
    assert saved["findings"] == [{"line": 10, "issue": "sql injection"}]
    assert saved["security_score"] == 6.5

    got = await store_a.get_code_review(saved["id"])
    assert got is not None and got["language"] == "python"

    assert {r["id"] for r in await store_a.list_code_reviews(language="python")} == {saved["id"]}
    assert await store_a.list_code_reviews(target="app/api/users.py") != []
    assert await store_a.list_code_reviews(status="open") != []

    assert await store_a.delete_code_review(saved["id"]) == 1
    assert await store_a.get_code_review(saved["id"]) is None


# ── Isolamento por tenant (banco-por-tenant, dual-db) ─────────────────────────
async def test_tenant_isolation(store_a, store_b):
    await store_a.save_database_schema(entity="only-in-a", database_name="mysql")
    await store_a.save_auth_policy(resource="res-a", auth_type="jwt")

    assert len(await store_a.list_database_schemas()) == 1
    # o tenant B tem SEU PRÓPRIO banco → não enxerga dados do A
    assert await store_b.list_database_schemas() == []
    assert await store_b.list_auth_policies() == []
    assert await store_b.get_auth_policy("res-a") is None
