"""
Services-MCP HTTP Server — FastAPI wrapper.

Wires ServicesHTTPEndpoints into a FastAPI application on port 8001.
"""

from fastapi import FastAPI, HTTPException, Query, Path
from contextlib import asynccontextmanager
import logging
import os

logger = logging.getLogger(__name__)


def create_services_http_server(services_registry):
    """
    Create FastAPI application for services-mcp HTTP endpoints.

    Args:
        services_registry: ServiceRegistry instance with postgres_sync attribute

    Returns:
        FastAPI application ready to serve HTTP requests
    """
    from .http_endpoints import ServicesHTTPEndpoints

    # Initialize endpoints
    endpoints = ServicesHTTPEndpoints(services_registry.postgres_sync)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info("✅ Services-MCP HTTP server starting (port 8001)")
        yield
        logger.info("🛑 Services-MCP HTTP server shutting down")

    app = FastAPI(
        title="services-mcp",
        description="Service registry and health checks API",
        version="1.0.0",
        lifespan=lifespan
    )

    # ========== Health ==========

    @app.get("/health")
    async def health():
        return {
            "status": "ok",
            "service": "services-mcp",
            "port": 8001
        }

    # ========== Services ==========

    @app.get("/services")
    async def get_services(
        environment: str = Query(None),
        status: str = Query(None),
        service_type: str = Query(None)
    ):
        result = endpoints.get_services(
            environment=environment,
            status=status,
            service_type=service_type
        )
        if result.get('status') == 200:
            return result
        raise HTTPException(
            status_code=result.get('status', 500),
            detail=result.get('error', 'internal_error')
        )

    @app.get("/services/{name}")
    async def get_service(name: str = Path(...)):
        result = endpoints.get_service(name)
        if result.get('status') == 200:
            return result
        raise HTTPException(
            status_code=result.get('status', 500),
            detail=result.get('error', 'internal_error')
        )

    @app.post("/services")
    async def post_services(
        name: str = Query(...),
        service_type: str = Query(...),
        host: str = Query(...),
        port: int = Query(...),
        health_check_url: str = Query(None),
        environment: str = Query("dev")
    ):
        result = endpoints.post_services(
            name=name,
            service_type=service_type,
            host=host,
            port=port,
            health_check_url=health_check_url,
            environment=environment
        )
        if result.get('status') == 201:
            return result
        raise HTTPException(
            status_code=result.get('status', 500),
            detail=result.get('error', 'internal_error')
        )

    @app.patch("/services/{name}")
    async def patch_service(
        name: str = Path(...),
        description: str = Query(None),
        health_check_url: str = Query(None),
        requires_auth: bool = Query(None)
    ):
        updates = {}
        if description is not None:
            updates['description'] = description
        if health_check_url is not None:
            updates['health_check_url'] = health_check_url
        if requires_auth is not None:
            updates['requires_auth'] = requires_auth

        result = endpoints.patch_service(name, **updates)
        if result.get('status') == 200:
            return result
        raise HTTPException(
            status_code=result.get('status', 500),
            detail=result.get('error', 'internal_error')
        )

    @app.get("/services/health")
    async def get_services_health():
        result = endpoints.get_services_health()
        if result.get('status') == 200:
            return result
        raise HTTPException(
            status_code=result.get('status', 500),
            detail=result.get('error', 'internal_error')
        )

    @app.post("/services/{name}/health-check")
    async def post_service_health_check(
        name: str = Path(...),
        status: str = Query(...),
        response_time_ms: float = Query(None)
    ):
        result = endpoints.post_service_health_check(
            name=name,
            status=status,
            response_time_ms=response_time_ms
        )
        if result.get('status') == 200:
            return result
        raise HTTPException(
            status_code=result.get('status', 500),
            detail=result.get('error', 'internal_error')
        )

    @app.delete("/services/{name}")
    async def delete_service(name: str = Path(...)):
        result = endpoints.delete_service(name)
        if result.get('status') == 200:
            return result
        raise HTTPException(
            status_code=result.get('status', 500),
            detail=result.get('error', 'internal_error')
        )

    return app


if __name__ == "__main__":
    import uvicorn

    # For local development
    from ..registry import ServiceRegistry

    registry = ServiceRegistry()
    app = create_services_http_server(registry)

    port = int(os.getenv("SERVICES_MCP_HTTP_PORT", "8001"))
    uvicorn.run(app, host="127.0.0.1", port=port)
