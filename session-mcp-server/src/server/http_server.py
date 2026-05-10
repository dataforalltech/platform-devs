"""
Session-MCP HTTP Server — FastAPI wrapper.

Wires SessionHTTPEndpoints into a FastAPI application on port 7100.
"""

from fastapi import FastAPI, HTTPException, Query, Path
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import logging
import os

logger = logging.getLogger(__name__)


def create_session_http_server(session_store):
    """
    Create FastAPI application for session-mcp HTTP endpoints.

    Args:
        session_store: SessionStore instance with postgres_sync attribute

    Returns:
        FastAPI application ready to serve HTTP requests
    """
    from .http_endpoints import SessionHTTPEndpoints

    # Initialize endpoints
    endpoints = SessionHTTPEndpoints(session_store.postgres_sync)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info("✅ Session-MCP HTTP server starting (port 7100)")
        yield
        logger.info("🛑 Session-MCP HTTP server shutting down")

    app = FastAPI(
        title="session-mcp",
        description="Session and task tracking API",
        version="1.0.0",
        lifespan=lifespan
    )

    # ========== Health ==========

    @app.get("/health")
    async def health():
        return {
            "status": "ok",
            "service": "session-mcp",
            "port": 7100
        }

    # ========== Sessions ==========

    @app.get("/sessions")
    async def get_sessions(
        status: str = Query(None),
        repo: str = Query(None),
        limit: int = Query(20)
    ):
        result = endpoints.get_sessions(status=status, repo=repo, limit=limit)
        if result.get('status') == 200:
            return result
        raise HTTPException(
            status_code=result.get('status', 500),
            detail=result.get('error', 'internal_error')
        )

    @app.get("/sessions/{session_id}")
    async def get_session(session_id: str = Path(...)):
        result = endpoints.get_session(session_id)
        if result.get('status') == 200:
            return result
        raise HTTPException(
            status_code=result.get('status', 500),
            detail=result.get('error', 'internal_error')
        )

    # ========== Tasks ==========

    @app.get("/sessions/{session_id}/tasks")
    async def list_session_tasks(
        session_id: str = Path(...),
        status: str = Query(None)
    ):
        result = endpoints.list_session_tasks(session_id, status=status)
        if result.get('status') == 200:
            return result
        raise HTTPException(
            status_code=result.get('status', 500),
            detail=result.get('error', 'internal_error')
        )

    @app.get("/sessions/{session_id}/tasks/{task_id}")
    async def get_task(
        session_id: str = Path(...),
        task_id: int = Path(...)
    ):
        result = endpoints.get_task(session_id, task_id)
        if result.get('status') == 200:
            return result
        raise HTTPException(
            status_code=result.get('status', 500),
            detail=result.get('error', 'internal_error')
        )

    # ========== Checkpoints ==========

    @app.get("/sessions/{session_id}/checkpoints")
    async def list_session_checkpoints(session_id: str = Path(...)):
        result = endpoints.list_session_checkpoints(session_id)
        if result.get('status') == 200:
            return result
        raise HTTPException(
            status_code=result.get('status', 500),
            detail=result.get('error', 'internal_error')
        )

    # ========== Artifacts ==========

    @app.get("/sessions/{session_id}/artifacts")
    async def list_session_artifacts(
        session_id: str = Path(...),
        artifact_type: str = Query(None)
    ):
        result = endpoints.list_session_artifacts(session_id, artifact_type=artifact_type)
        if result.get('status') == 200:
            return result
        raise HTTPException(
            status_code=result.get('status', 500),
            detail=result.get('error', 'internal_error')
        )

    # ========== Suggestions ==========

    @app.get("/sessions/{session_id}/suggestions")
    async def list_session_suggestions(session_id: str = Path(...)):
        result = endpoints.list_session_suggestions(session_id)
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
    from ..store import SessionStore

    store = SessionStore()
    app = create_session_http_server(store)

    port = int(os.getenv("SESSION_MCP_HTTP_PORT", "7100"))
    uvicorn.run(app, host="127.0.0.1", port=port)
