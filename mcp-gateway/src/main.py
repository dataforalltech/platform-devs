"""MCP Gateway — manifest-driven policy enforcement point."""

from __future__ import annotations

from contextlib import asynccontextmanager
import os

import uvicorn
from fastapi import FastAPI, HTTPException

from src.middleware.audit_logger import (
    AuditUnavailable,
    assert_audit_available,
)
from src.middleware.rate_limiter import close_redis
from src.proxy.router import setup_proxy_routes
from src.registry import RegistryUnavailable, runtime_registry

_REQUIRED_CONFIGURATION = (
    "GATEWAY_PDP_URL",
    "GATEWAY_TOKEN_EXCHANGE_URL",
    "GATEWAY_CONTEXT_SIGNING_KEY",
    "GATEWAY_AS_ISSUER",
    "GATEWAY_AS_JWKS_URL",
    "GATEWAY_RESOURCE",
    "GATEWAY_RATE_LIMITS_JSON",
    "REDIS_HOST",
    "REDIS_PORT",
    "REDIS_PASSWORD",
    "PG_HOST",
    "PG_PORT",
    "PG_DB",
    "PG_USER",
    "PG_PASSWORD",
)


def validate_configuration() -> None:
    missing = [name for name in _REQUIRED_CONFIGURATION if not os.environ.get(name)]
    if missing:
        raise RuntimeError(f"gateway configuration missing: {', '.join(missing)}")


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Security dependencies are mandatory: startup fails instead of exposing a
    # partially governed proxy.
    validate_configuration()
    runtime_registry.list()
    await assert_audit_available()
    yield
    await close_redis()


app = FastAPI(
    title="MCP Gateway",
    version="2.0.0",
    description="Manifest-driven MCP policy enforcement point",
    lifespan=lifespan,
)
setup_proxy_routes(app)


@app.get("/v1/health/live")
async def health_live() -> dict[str, str]:
    return {"status": "ok", "service": "mcp-gateway"}


@app.get("/v1/health/ready")
async def health_ready() -> dict[str, str]:
    try:
        validate_configuration()
        runtime_registry.list()
        await assert_audit_available()
    except (RuntimeError, RegistryUnavailable, AuditUnavailable) as exc:
        raise HTTPException(status_code=503, detail="gateway dependencies unavailable") from exc
    return {"status": "ready", "service": "mcp-gateway"}


def main() -> None:
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.environ.get("MCP_PORT", "8080")),
        log_level="info",
    )


if __name__ == "__main__":
    main()
