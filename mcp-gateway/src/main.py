"""MCP Gateway — Central proxy for multi-tenant, multi-protocol MCP access."""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
import uvicorn
import psycopg2

from src.proxy.router import setup_proxy_routes
from src.middleware.audit_logger import init_audit_table, close_connection as close_pg
from src.middleware.rate_limiter import close_redis
from src.persistence.tool_interceptor import ToolInterceptor

db_conn = None
interceptor = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    # Startup
    global db_conn, interceptor
    init_audit_table()

    try:
        db_conn = psycopg2.connect(
            host=os.getenv("PG_HOST", "postgres"),
            port=int(os.getenv("PG_PORT", "5432")),
            user=os.getenv("PG_USER", "platform"),
            password=os.getenv("PG_PASSWORD", "staging_password_123"),
            database=os.getenv("PG_DB", "platform_staging")
        )
        interceptor = ToolInterceptor(db_conn)
        print("✅ Gateway: Tool interceptor initialized with PostgreSQL")
        # Setup routes AFTER interceptor is initialized
        setup_proxy_routes(app, interceptor)
        print("✅ Gateway: Proxy routes configured with interceptor")
    except Exception as e:
        print(f"⚠️  Gateway: Failed to initialize interceptor: {e}")
        import traceback
        traceback.print_exc()
        # Setup routes without interceptor
        setup_proxy_routes(app, None)

    yield
    # Shutdown
    if db_conn:
        db_conn.close()
    close_pg()
    await close_redis()

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

def main() -> None:
    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="info")

if __name__ == "__main__":
    main()
