"""
Config-MCP HTTP Server — FastAPI wrapper.

Wires ConfigHTTPEndpoints into a FastAPI application on port 7099.
"""

from fastapi import FastAPI, HTTPException, Query, Path
from contextlib import asynccontextmanager
import logging
import os

logger = logging.getLogger(__name__)


def create_config_http_server(config_store, tenant_id: str = "platform_dev"):
    """
    Create FastAPI application for config-mcp HTTP endpoints.

    Args:
        config_store: ConfigStore instance with postgres_sync attribute
        tenant_id: Current tenant context (default: platform_dev)

    Returns:
        FastAPI application ready to serve HTTP requests
    """
    from .http_endpoints import ConfigHTTPEndpoints

    # Initialize endpoints
    endpoints = ConfigHTTPEndpoints(config_store.postgres_sync, tenant_id)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info("✅ Config-MCP HTTP server starting (port 7099)")
        yield
        logger.info("🛑 Config-MCP HTTP server shutting down")

    app = FastAPI(
        title="config-mcp",
        description="Configuration and credentials API",
        version="1.0.0",
        lifespan=lifespan
    )

    # ========== Health ==========

    @app.get("/health")
    async def health():
        return {
            "status": "ok",
            "service": "config-mcp",
            "port": 7099,
            "tenant_id": tenant_id
        }

    # ========== Credentials ==========

    @app.get("/credentials/list")
    async def get_credentials_list(
        namespace: str = Query(None),
        include_metadata: bool = Query(True)
    ):
        result = endpoints.get_credentials_list(
            namespace=namespace,
            include_metadata=include_metadata
        )
        if result.get('status') == 200:
            return result
        raise HTTPException(
            status_code=result.get('status', 500),
            detail=result.get('error', 'internal_error')
        )

    @app.get("/credentials/metadata")
    async def get_credentials_metadata(
        namespace: str = Query(...),
        key: str = Query(...)
    ):
        result = endpoints.get_credentials_metadata(namespace, key)
        if result.get('status') == 200:
            return result
        raise HTTPException(
            status_code=result.get('status', 500),
            detail=result.get('error', 'internal_error')
        )

    @app.post("/credentials/validate")
    async def post_credentials_validate(
        namespace: str = Query(...),
        key: str = Query(...)
    ):
        result = endpoints.post_credentials_validate(namespace, key)
        if result.get('status') == 200:
            return result
        raise HTTPException(
            status_code=result.get('status', 500),
            detail=result.get('error', 'internal_error')
        )

    @app.post("/credentials/rotate")
    async def post_credentials_rotate(
        namespace: str = Query(...),
        key: str = Query(...),
        new_value: str = Query(...)
    ):
        result = endpoints.post_credentials_rotate(namespace, key, new_value)
        if result.get('status') == 200:
            return result
        raise HTTPException(
            status_code=result.get('status', 500),
            detail=result.get('error', 'internal_error')
        )

    @app.delete("/credentials")
    async def delete_credentials(
        namespace: str = Query(...),
        key: str = Query(...)
    ):
        result = endpoints.delete_credentials(namespace, key)
        if result.get('status') == 200:
            return result
        raise HTTPException(
            status_code=result.get('status', 500),
            detail=result.get('error', 'internal_error')
        )

    @app.get("/credentials/namespaces")
    async def get_credentials_namespaces():
        result = endpoints.get_credentials_namespaces()
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
    from ..store import ConfigStore

    store = ConfigStore()
    app = create_config_http_server(store)

    port = int(os.getenv("CONFIG_MCP_HTTP_PORT", "7099"))
    uvicorn.run(app, host="127.0.0.1", port=port)
