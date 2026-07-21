from app.api import api_router
from app.api.health import health_router
from app.api.internal import router as internal_router
from app.modules.products.routers import router as products_router
from app.modules.projects.routers import router as projects_router


def _effective_routes(router):
    """Return materialized routes across FastAPI's eager and nested routers."""
    routes = []
    for route in router.routes:
        effective_route_contexts = getattr(route, "effective_route_contexts", None)
        if callable(effective_route_contexts):
            routes.extend(effective_route_contexts())
        elif hasattr(route, "path"):
            routes.append(route)
    return routes


def test_public_and_private_api_contracts_are_materialized():
    paths = {route.path for route in _effective_routes(api_router)}
    expected = {
        "/api/v1/products",
        "/api/v1/products/{product_id}",
        "/api/v1/projects",
        "/api/v1/projects/{project_id}",
        "/api/v1/projects/{project_id}/repositories",
        "/api/v1/projects/{project_id}/repositories/{binding_id}",
        "/api/internal/mcp/products",
        "/api/internal/mcp/products/{product_id}",
        "/api/internal/mcp/projects",
        "/api/internal/mcp/projects/{project_id}",
        "/api/internal/mcp/projects/{project_id}/repositories",
        "/api/internal/mcp/repositories/{binding_id}",
    }
    assert expected <= paths
    assert {route.path for route in _effective_routes(health_router)} == {
        "/health/live",
        "/health/ready",
    }


def test_internal_routes_are_excluded_from_openapi():
    assert all(
        route.include_in_schema is False
        for route in _effective_routes(api_router)
        if route.path.startswith("/api/internal/")
    )


def test_list_status_filters_reject_unknown_values_at_the_http_boundary():
    routes = [
        (products_router, "listProducts", None, "active"),
        (projects_router, "listProjects", None, "completed"),
        (internal_router, None, "/internal/mcp/products", "active"),
        (internal_router, None, "/internal/mcp/projects", "completed"),
    ]
    for router, operation_id, path, valid_value in routes:
        route = next(
            item
            for item in router.routes
            if (operation_id and getattr(item, "operation_id", None) == operation_id)
            or (
                path
                and getattr(item, "path", None) == path
                and "GET" in getattr(item, "methods", set())
            )
        )
        status_field = next(
            field for field in route.dependant.query_params if field.alias == "status"
        )
        _value, invalid_errors = status_field.validate(
            "unknown",
            {},
            loc=("query", "status"),
        )
        valid, valid_errors = status_field.validate(
            valid_value,
            {},
            loc=("query", "status"),
        )
        assert invalid_errors
        assert not valid_errors
        assert valid == valid_value
