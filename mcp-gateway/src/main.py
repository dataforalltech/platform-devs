"""MCP Gateway — Central proxy for multi-tenant, multi-protocol MCP access."""
from __future__ import annotations

from contextlib import asynccontextmanager
from fastapi import FastAPI
import uvicorn

from src.proxy.router import setup_proxy_routes
from src.middleware.audit_logger import init_audit_table, close_connection as close_pg

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    # Startup
    init_audit_table()
    yield
    # Shutdown
    close_pg()

app = FastAPI(
    title="MCP Gateway",
    version="1.0.0",
    description="Central proxy for multi-tenant, multi-protocol access to Model Context Protocol servers",
    lifespan=lifespan,
)

@app.get("/health")
async def health():
    return {"status": "ok", "service": "mcp-gateway"}

@app.get("/")
async def root():
    return {
        "service": "mcp-gateway",
        "version": "1.0.0",
        "endpoints": [
            "/health",
            "/mcp",
            "/mcp/{mcp_name}/tools",
            "/mcp/{mcp_name}/tools/call",
            "/admin/quotas",
        ],
    }

setup_proxy_routes(app)

def main() -> None:
    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="info")

if __name__ == "__main__":
    main()
