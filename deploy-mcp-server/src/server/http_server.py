"""
Deploy-MCP HTTP Server — FastAPI wrapper.

Wires DeployHTTPEndpoints into a FastAPI application on port 8002.
"""

from fastapi import FastAPI, HTTPException, Query, Path
from contextlib import asynccontextmanager
import logging
import os

logger = logging.getLogger(__name__)


def create_deploy_http_server(deploy_manager):
    """
    Create FastAPI application for deploy-mcp HTTP endpoints.

    Args:
        deploy_manager: DeployManager instance with postgres_sync attribute

    Returns:
        FastAPI application ready to serve HTTP requests
    """
    from .http_endpoints import DeployHTTPEndpoints

    # Initialize endpoints
    endpoints = DeployHTTPEndpoints(deploy_manager.postgres_sync)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info("✅ Deploy-MCP HTTP server starting (port 8002)")
        yield
        logger.info("🛑 Deploy-MCP HTTP server shutting down")

    app = FastAPI(
        title="deploy-mcp",
        description="GitHub and ACR deployment API",
        version="1.0.0",
        lifespan=lifespan
    )

    # ========== Health ==========

    @app.get("/v1/health")
    async def health():
        return {"status": "ok", "service": "deploy-mcp"}

    # ========== Repositories ==========

    @app.get("/repositories")
    async def get_repositories(
        organization: str = Query(None),
        status: str = Query(None)
    ):
        result = endpoints.get_repositories(
            organization=organization,
            status=status
        )
        if result.get('status') == 200:
            return result
        raise HTTPException(
            status_code=result.get('status', 500),
            detail=result.get('error', 'internal_error')
        )

    @app.get("/repositories/{name}")
    async def get_repository(name: str = Path(...)):
        result = endpoints.get_repository(name)
        if result.get('status') == 200:
            return result
        raise HTTPException(
            status_code=result.get('status', 500),
            detail=result.get('error', 'internal_error')
        )

    @app.post("/repositories")
    async def post_repositories(
        name: str = Query(...),
        owner: str = Query(...),
        url: str = Query(...),
        description: str = Query(None),
        base_branch: str = Query("develop"),
        main_branch: str = Query("main"),
        language: str = Query(None)
    ):
        result = endpoints.post_repositories(
            name=name,
            owner=owner,
            url=url,
            description=description,
            base_branch=base_branch,
            main_branch=main_branch,
            language=language
        )
        if result.get('status') == 201:
            return result
        raise HTTPException(
            status_code=result.get('status', 500),
            detail=result.get('error', 'internal_error')
        )

    @app.get("/repositories/{name}/branches")
    async def get_repository_branches(name: str = Path(...)):
        result = endpoints.get_repository_branches(name)
        if result.get('status') == 200:
            return result
        raise HTTPException(
            status_code=result.get('status', 500),
            detail=result.get('error', 'internal_error')
        )

    @app.get("/repositories/{name}/workflows")
    async def get_repository_workflows(name: str = Path(...)):
        result = endpoints.get_repository_workflows(name)
        if result.get('status') == 200:
            return result
        raise HTTPException(
            status_code=result.get('status', 500),
            detail=result.get('error', 'internal_error')
        )

    @app.get("/repositories/{name}/acr-images")
    async def get_repository_acr_images(
        name: str = Path(...),
        limit: int = Query(20)
    ):
        result = endpoints.get_repository_acr_images(name, limit=limit)
        if result.get('status') == 200:
            return result
        raise HTTPException(
            status_code=result.get('status', 500),
            detail=result.get('error', 'internal_error')
        )

    @app.post("/repositories/{name}/workflow-run")
    async def post_repository_workflow_run(
        name: str = Path(...),
        workflow_id: str = Query(...),
        ref: str = Query(...)
    ):
        result = endpoints.post_repository_workflow_run(
            name=name,
            workflow_id=workflow_id,
            ref=ref
        )
        if result.get('status') == 202:
            return result
        raise HTTPException(
            status_code=result.get('status', 500),
            detail=result.get('error', 'internal_error')
        )

    @app.get("/repositories/{name}/pull-requests")
    async def get_repository_pull_requests(
        name: str = Path(...),
        state: str = Query("open")
    ):
        result = endpoints.get_repository_pull_requests(name, state=state)
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
    from ..manager import DeployManager

    manager = DeployManager()
    app = create_deploy_http_server(manager)

    port = int(os.getenv("DEPLOY_MCP_HTTP_PORT", "8002"))
    uvicorn.run(app, host="127.0.0.1", port=port)
