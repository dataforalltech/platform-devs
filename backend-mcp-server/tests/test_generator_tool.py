"""Unidade dos geradores determinísticos de backend (COMPUTE PURO — sem DB, sem LLM).

Estes testes NÃO tocam o MySQL: os geradores são funções puras ``spec -> dict``.
Cada gerador tem ao menos uma fixture-spec com asserts em marcadores-chave do output,
um guard de spec inválida, mais um teste global de DETERMINISMO (mesma spec chamada
2x → output idêntico)."""

from __future__ import annotations

import pytest

from src.tools.generator_tool import (
    generate_api_contract,
    generate_auth_policy,
    generate_database_schema,
    generate_event_contracts,
    generate_fastapi_router,
    generate_migration,
    generate_repository_layer,
    generate_service_layer,
)

# ── Fixtures de spec (reaproveitadas nos testes de conteúdo e de determinismo) ─
ROUTER_SPEC = {
    "resource": "user",
    "routes": [
        {"method": "get", "path": "/{user_id}", "handler": "get_user"},
        {"method": "post", "path": "/", "handler": "create_user"},
    ],
}
SERVICE_SPEC = {"entity": "order-item", "methods": ["create", {"name": "get"}, "list"]}
REPOSITORY_SPEC = {
    "entity": "customer",
    "fields": [{"name": "id", "type": "integer"}, {"name": "email", "type": "string"}],
}
DB_SCHEMA_SPEC = {
    "tables": [
        {
            "name": "users",
            "columns": [
                {"name": "id", "type": "INTEGER", "pk": True},
                {"name": "email", "type": "TEXT"},
                {"name": "org_id", "type": "INTEGER", "fk": "orgs(id)"},
            ],
        }
    ]
}
MIGRATION_SPEC = {
    "revision": "abc123",
    "down_revision": "def456",
    "message": "add users table",
    "ops": [
        {"op": "create_table", "table": "users"},
        {"op": "add_column", "table": "users", "column": "email", "type": "string"},
    ],
}
API_CONTRACT_SPEC = {
    "title": "Users API",
    "version": "2.0.0",
    "paths": [
        {"path": "/users", "method": "get", "summary": "List users", "operationId": "list_users"},
        {"path": "/users", "method": "post", "summary": "Create user"},
    ],
}
AUTH_POLICY_SPEC = {
    "title": "Backend RBAC",
    "roles": ["admin", "user"],
    "resources": ["users", "orders"],
    "rules": [
        {"role": "admin", "resource": "users", "actions": ["read", "write"], "effect": "allow"},
        {"role": "user", "resource": "orders", "actions": "read", "effect": "allow"},
    ],
}
EVENTS_SPEC = {
    "version": "1.0",
    "events": [
        {"name": "OrderPlaced", "fields": {"order_id": "string", "amount": "float"}},
        {"name": "UserCreated", "fields": [{"name": "id", "type": "integer"}]},
    ],
}


# ── 1. Router FastAPI ─────────────────────────────────────────────────────────
def test_generate_fastapi_router_markers():
    out = generate_fastapi_router(ROUTER_SPEC)
    art = out["artifact"]
    assert out["kind"] == "fastapi_router"
    assert out["filename"] == "user_router.py"
    assert 'APIRouter(prefix="/user"' in art
    assert '@router.get("/{user_id}")' in art
    assert "async def get_user(user_id: str) -> dict[str, Any]:" in art
    assert "async def create_user() -> dict[str, Any]:" in art


def test_generate_fastapi_router_rejects_unsupported_method():
    out = generate_fastapi_router({"resource": "x", "routes": [{"method": "trace", "path": "/"}]})
    assert out["error"] == "unsupported_method"


def test_generate_fastapi_router_requires_routes():
    assert generate_fastapi_router({"resource": "x", "routes": []})["error"] == "missing_routes"


# ── 2. Camada de Service ──────────────────────────────────────────────────────
def test_generate_service_layer_markers():
    out = generate_service_layer(SERVICE_SPEC)
    art = out["artifact"]
    assert out["kind"] == "service_layer"
    assert out["filename"] == "order_item_service.py"
    assert "class OrderItemService:" in art
    assert "async def create(self, payload: dict[str, Any]) -> dict[str, Any]:" in art
    assert "async def get(self, entity_id: Any) -> dict[str, Any] | None:" in art
    assert "async def list(self, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:" in art


def test_generate_service_layer_defaults_to_crud():
    art = generate_service_layer({"entity": "thing"})["artifact"]
    for method in ("create", "get", "list", "update", "delete"):
        assert f"async def {method}(" in art


def test_generate_service_layer_requires_entity():
    assert generate_service_layer({"entity": ""})["error"] == "missing_entity"


# ── 3. Repositório ORM async ──────────────────────────────────────────────────
def test_generate_repository_layer_markers():
    out = generate_repository_layer(REPOSITORY_SPEC)
    art = out["artifact"]
    assert out["kind"] == "repository_layer"
    assert out["filename"] == "customer_repository.py"
    assert "class CustomerRepository:" in art
    assert '__tablename__ = "customer"' in art
    assert "session: AsyncSession" in art
    assert "id (integer), email (string)" in art
    assert "async def create(self, data: dict[str, Any]) -> Any:" in art


def test_generate_repository_layer_requires_entity():
    assert generate_repository_layer({"fields": []})["error"] == "missing_entity"


# ── 4. DDL SQL ────────────────────────────────────────────────────────────────
def test_generate_database_schema_markers():
    out = generate_database_schema(DB_SCHEMA_SPEC)
    art = out["artifact"]
    assert out["kind"] == "database_schema"
    assert out["filename"] == "schema.sql"
    assert "CREATE TABLE users (" in art
    assert "    id INTEGER" in art
    assert "    PRIMARY KEY (id)" in art
    assert "    FOREIGN KEY (org_id) REFERENCES orgs(id)" in art


def test_generate_database_schema_requires_tables():
    assert generate_database_schema({"tables": []})["error"] == "missing_tables"


def test_generate_database_schema_rejects_column_without_name():
    out = generate_database_schema({"tables": [{"name": "t", "columns": [{"type": "TEXT"}]}]})
    assert out["error"] == "column_missing_name"


# ── 5. Migration alembic ──────────────────────────────────────────────────────
def test_generate_migration_markers():
    out = generate_migration(MIGRATION_SPEC)
    art = out["artifact"]
    assert out["kind"] == "migration"
    assert out["filename"] == "abc123_migration.py"
    assert 'revision = "abc123"' in art
    assert 'down_revision = "def456"' in art
    assert "def upgrade() -> None:" in art
    assert "def downgrade() -> None:" in art
    assert 'op.create_table("users")' in art
    assert 'op.add_column("users", sa.Column("email", sa.String()))' in art
    # downgrade é o inverso (add_column vira drop_column, ordem invertida)
    up_idx = art.index("def upgrade")
    down_idx = art.index("def downgrade")
    assert 'op.drop_column("users", "email")' in art[down_idx:]
    assert art.index('op.drop_column("users", "email")') > up_idx


def test_generate_migration_rejects_unsupported_op():
    out = generate_migration({"revision": "r1", "ops": [{"op": "frobnicate", "table": "t"}]})
    assert out["error"] == "unsupported_op"


def test_generate_migration_requires_ops():
    assert generate_migration({"revision": "r1", "ops": []})["error"] == "missing_ops"


# ── 6. Contrato de API (OpenAPI 3.1) ──────────────────────────────────────────
def test_generate_api_contract_markers():
    out = generate_api_contract(API_CONTRACT_SPEC)
    art = out["artifact"]
    assert out["kind"] == "api_contract"
    assert out["filename"] == "openapi.yaml"
    assert "openapi: 3.1.0" in art
    assert 'title: "Users API"' in art
    assert 'version: "2.0.0"' in art
    assert '"/users":' in art
    assert "    get:" in art and "    post:" in art
    assert "operationId: list_users" in art


def test_generate_api_contract_requires_paths():
    assert generate_api_contract({"title": "x", "paths": []})["error"] == "missing_paths"


def test_generate_api_contract_rejects_unsupported_method():
    out = generate_api_contract({"title": "x", "paths": [{"path": "/a", "method": "connect"}]})
    assert out["error"] == "unsupported_method"


# ── 7. Política RBAC ──────────────────────────────────────────────────────────
def test_generate_auth_policy_markers():
    out = generate_auth_policy(AUTH_POLICY_SPEC)
    art = out["artifact"]
    assert out["kind"] == "auth_policy"
    assert out["filename"] == "rbac_policy.md"
    assert "# Backend RBAC" in art
    assert "## Roles" in art and "## Resources" in art and "## Rules" in art
    assert "| Role | Resource | Actions | Effect |" in art
    assert "| admin | users | read, write | allow |" in art


def test_generate_auth_policy_requires_roles():
    assert generate_auth_policy({"resources": ["x"]})["error"] == "missing_roles"


def test_generate_auth_policy_requires_resources():
    assert generate_auth_policy({"roles": ["x"]})["error"] == "missing_resources"


# ── 8. Contratos de eventos ───────────────────────────────────────────────────
def test_generate_event_contracts_markers():
    out = generate_event_contracts(EVENTS_SPEC)
    art = out["artifact"]
    assert out["kind"] == "event_contracts"
    assert out["filename"] == "events.yaml"
    assert 'version: "1.0"' in art
    assert "  OrderPlaced:" in art and "  UserCreated:" in art
    assert "    type: object" in art
    assert "      order_id:" in art
    assert "        type: string" in art
    assert "        type: number" in art  # amount: float → number
    # eventos ordenados alfabeticamente (OrderPlaced antes de UserCreated)
    assert art.index("OrderPlaced") < art.index("UserCreated")


def test_generate_event_contracts_requires_events():
    assert generate_event_contracts({"events": []})["error"] == "missing_events"


def test_generate_event_contracts_rejects_event_without_name():
    out = generate_event_contracts({"events": [{"fields": {}}]})
    assert out["error"] == "event_missing_name"


# ── Determinismo global (mesma spec chamada 2x → output idêntico) ─────────────
@pytest.mark.parametrize(
    "fn,spec",
    [
        (generate_fastapi_router, ROUTER_SPEC),
        (generate_service_layer, SERVICE_SPEC),
        (generate_repository_layer, REPOSITORY_SPEC),
        (generate_database_schema, DB_SCHEMA_SPEC),
        (generate_migration, MIGRATION_SPEC),
        (generate_api_contract, API_CONTRACT_SPEC),
        (generate_auth_policy, AUTH_POLICY_SPEC),
        (generate_event_contracts, EVENTS_SPEC),
    ],
)
def test_generators_are_deterministic(fn, spec):
    assert fn(dict(spec)) == fn(dict(spec))


def test_event_field_ordering_is_stable_regardless_of_input_order():
    # dicts de fields com mesma composição mas ordens diferentes → mesmo output.
    a = generate_event_contracts({"events": [{"name": "E", "fields": {"a": "string", "b": "integer"}}]})
    b = generate_event_contracts({"events": [{"name": "E", "fields": {"b": "integer", "a": "string"}}]})
    assert a == b
