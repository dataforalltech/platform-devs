"""Testes das tools do backend-mcp-server.

Foco: a saída deve REFLETIR/DERIVAR dos inputs. Cada teste passa inputs custom e
afirma que eles reaparecem na saída, e que os campos derivados (índices, defaults,
opcionais) seguem o input fornecido — não valores canônicos genéricos.
"""

from __future__ import annotations

from src.tools.backend_tools import (
    analyze_backend_requirement,
    generate_api_contract,
    generate_auth_policy,
    generate_database_schema,
    generate_fastapi_router,
    generate_migration,
    generate_nestjs_controller,
    generate_openapi_spec,
    generate_repository_layer,
    generate_service_layer,
    map_integration_flow,
    optimize_query,
    review_backend_code,
)


# ── analyze_backend_requirement ───────────────────────────────────────────────
def test_analyze_backend_requirement_reflects_input():
    result = analyze_backend_requirement(
        requirement="Users can reset their password", context={"module": "auth"}
    )
    assert result["analysis"] == "Analyzed backend requirement: Users can reset their password"
    assert result["context"] == {"module": "auth"}
    assert "read" in result["permissions"]


def test_analyze_backend_requirement_default_context():
    result = analyze_backend_requirement(requirement="R")
    # Sem contexto → dict vazio (não None), não vaza valor antigo.
    assert result["context"] == {}
    assert result["entities"] == ["example_entity"]


# ── generate_api_contract ─────────────────────────────────────────────────────
def test_generate_api_contract_preserves_schemas():
    req = {"type": "object", "properties": {"email": {"type": "string"}}}
    res = {"type": "object", "properties": {"id": {"type": "integer"}}}
    result = generate_api_contract(
        endpoint="/v1/users",
        method="POST",
        description="Create user",
        request_schema=req,
        response_schema=res,
    )
    assert result["endpoint"] == "/v1/users"
    assert result["method"] == "POST"
    assert result["description"] == "Create user"
    assert result["request_schema"] == req
    assert result["response_schema"] == res
    assert 401 in result["status_codes"]


def test_generate_api_contract_default_schemas_empty():
    result = generate_api_contract(endpoint="/x", method="GET", description="d")
    assert result["request_schema"] == {}
    assert result["response_schema"] == {}


# ── generate_auth_policy ──────────────────────────────────────────────────────
def test_generate_auth_policy_reflects_roles_and_sensitivity():
    result = generate_auth_policy(
        resource="invoices",
        auth_type="oauth2",
        roles=["finance", "admin"],
        data_sensitivity="confidential",
    )
    assert result["resource"] == "invoices"
    assert result["auth_type"] == "oauth2"
    assert result["roles"] == ["finance", "admin"]
    assert result["data_sensitivity"] == "confidential"
    assert result["encryption"] == "AES-256"


def test_generate_auth_policy_default_sensitivity():
    result = generate_auth_policy(resource="r", auth_type="jwt", roles=[])
    # Sem sensibilidade → default explícito 'internal'.
    assert result["data_sensitivity"] == "internal"


# ── generate_database_schema ──────────────────────────────────────────────────
def test_generate_database_schema_index_derived_from_entity():
    attrs = [{"name": "id", "type": "uuid"}, {"name": "email", "type": "varchar"}]
    result = generate_database_schema(
        entity="customer",
        attributes=attrs,
        database="postgres",
        relationships=[{"to": "order", "type": "one_to_many"}],
    )
    assert result["entity"] == "customer"
    assert result["database"] == "postgres"
    assert result["attributes"] == attrs
    # Índice derivado do nome da entidade (não constante fixa).
    assert result["indexes"] == ["idx_customer_id"]
    assert result["relationships"] == [{"to": "order", "type": "one_to_many"}]


def test_generate_database_schema_default_relationships_empty():
    result = generate_database_schema(entity="product", attributes=[], database="mysql")
    assert result["relationships"] == []
    assert result["indexes"] == ["idx_product_id"]


# ── generate_fastapi_router ───────────────────────────────────────────────────
def test_generate_fastapi_router_tags_from_name():
    result = generate_fastapi_router(
        name="orders", base_path="/v1/orders", endpoints=[{"path": "/", "method": "GET"}]
    )
    assert result["router_name"] == "orders"
    assert result["base_path"] == "/v1/orders"
    assert result["endpoints"] == [{"path": "/", "method": "GET"}]
    assert result["tags"] == ["orders"]


def test_generate_fastapi_router_default_endpoints_empty():
    result = generate_fastapi_router(name="health", base_path="/health")
    assert result["endpoints"] == []


# ── generate_nestjs_controller ────────────────────────────────────────────────
def test_generate_nestjs_controller_service_slug_from_name():
    result = generate_nestjs_controller(
        name="UserProfile", base_path="/profile", methods=[{"name": "findAll"}]
    )
    assert result["controller_name"] == "UserProfile"
    assert result["base_path"] == "/profile"
    assert result["methods"] == [{"name": "findAll"}]
    # Serviço derivado do nome em lowercase.
    assert result["services"] == ["userprofile.service"]


def test_generate_nestjs_controller_default_methods_empty():
    result = generate_nestjs_controller(name="Ping", base_path="/ping")
    assert result["methods"] == []
    assert result["services"] == ["ping.service"]


# ── generate_migration ────────────────────────────────────────────────────────
def test_generate_migration_reflects_title_and_operations():
    ops = [{"op": "create_table", "table": "users"}]
    result = generate_migration(title="create_users", operations=ops, database="postgres")
    assert result["migration_name"] == "create_users"
    assert result["operations"] == ops
    assert result["database"] == "postgres"
    assert "rollback" in result


# ── generate_repository_layer ─────────────────────────────────────────────────
def test_generate_repository_layer_custom_orm():
    result = generate_repository_layer(entity="account", database="postgres", orm="prisma")
    assert result["entity"] == "account"
    assert result["database"] == "postgres"
    assert result["orm"] == "prisma"
    assert "create" in result["methods"]


def test_generate_repository_layer_default_orm():
    result = generate_repository_layer(entity="wallet", database="mysql")
    # Sem ORM → default 'sqlalchemy'.
    assert result["orm"] == "sqlalchemy"


# ── generate_service_layer ────────────────────────────────────────────────────
def test_generate_service_layer_reflects_methods_and_deps():
    result = generate_service_layer(
        name="PaymentService",
        methods=[{"name": "charge"}, {"name": "refund"}],
        dependencies=["gateway_client"],
    )
    assert result["service_name"] == "PaymentService"
    assert result["methods"] == [{"name": "charge"}, {"name": "refund"}]
    assert result["dependencies"] == ["gateway_client"]


def test_generate_service_layer_default_dependencies_empty():
    result = generate_service_layer(name="NoopService", methods=[])
    assert result["dependencies"] == []


# ── generate_openapi_spec ─────────────────────────────────────────────────────
def test_generate_openapi_spec_paths_derived_from_endpoints():
    result = generate_openapi_spec(
        api_name="Billing API",
        version="2.1.0",
        endpoints=["/invoices", "/payments"],
        base_url="https://api.example.com",
    )
    assert result["info"] == {"title": "Billing API", "version": "2.1.0"}
    assert result["servers"] == [{"url": "https://api.example.com"}]
    # Paths derivam de cada endpoint fornecido.
    assert set(result["paths"].keys()) == {"/invoices", "/payments"}


def test_generate_openapi_spec_default_base_url():
    result = generate_openapi_spec(api_name="A", version="1", endpoints=[])
    assert result["servers"] == [{"url": "http://localhost:8000"}]
    assert result["paths"] == {}


# ── map_integration_flow ──────────────────────────────────────────────────────
def test_map_integration_flow_custom_auth():
    result = map_integration_flow(
        integration_name="stripe_sync",
        external_service="Stripe",
        endpoints=["/charges"],
        auth_type="bearer",
    )
    assert result["integration_name"] == "stripe_sync"
    assert result["external_service"] == "Stripe"
    assert result["endpoints"] == ["/charges"]
    assert result["auth_type"] == "bearer"
    assert result["retry_policy"] == "exponential_backoff"


def test_map_integration_flow_default_auth_and_endpoints():
    result = map_integration_flow(integration_name="i", external_service="s")
    assert result["auth_type"] == "api_key"
    assert result["endpoints"] == []


# ── optimize_query ────────────────────────────────────────────────────────────
def test_optimize_query_reflects_query_and_database():
    result = optimize_query(
        query="SELECT * FROM orders WHERE user_id = 1",
        database="postgres",
        table_schema={"orders": {"columns": ["id", "user_id"]}},
    )
    assert result["original_query"] == "SELECT * FROM orders WHERE user_id = 1"
    assert result["database"] == "postgres"
    assert "add_index" in result["optimizations"]
    assert result["recommendations"]


# ── review_backend_code ───────────────────────────────────────────────────────
def test_review_backend_code_custom_focus():
    result = review_backend_code(code="def f(): pass", language="python", focus=["security", "readability"])
    assert result["language"] == "python"
    assert result["focus_areas"] == ["security", "readability"]
    assert result["issues"] == []
    assert isinstance(result["security_score"], int)


def test_review_backend_code_default_focus():
    result = review_backend_code(code="x = 1", language="typescript")
    # Sem foco → default explícito.
    assert result["focus_areas"] == ["security", "performance"]
