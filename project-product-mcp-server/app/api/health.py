"""Private management liveness and dependency readiness probes."""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, HTTPException
from platform_database import get_pool_for_tenant
from pydantic import BaseModel

from app.core.config import settings

logger = logging.getLogger(__name__)
health_router = APIRouter(prefix="/health", tags=["Health"])

_SCHEMA_CHECKS = {
    "postgresql": (
        "SELECT COUNT(*) FROM information_schema.tables "
        "WHERE table_schema = current_schema() AND table_name IN ($1, $2, $3, $4)",
        (
            "portfolio_products",
            "portfolio_projects",
            "portfolio_project_repository_bindings",
            "portfolio_idempotency_keys",
        ),
    ),
    "mysql": (
        "SELECT COUNT(*) FROM information_schema.tables "
        "WHERE table_schema = DATABASE() AND table_name IN ($1, $2, $3, $4)",
        (
            "PORTFOLIO_PRODUCTS",
            "PORTFOLIO_PROJECTS",
            "PORTFOLIO_PROJECT_REPOSITORY_BINDINGS",
            "PORTFOLIO_IDEMPOTENCY_KEYS",
        ),
    ),
}


class HealthResponse(BaseModel):
    status: str


class ReadinessResponse(BaseModel):
    status: str
    tenant_registry: str
    tenant_database: str
    latency_ms: float


@health_router.get("/live", response_model=HealthResponse, operation_id="healthLive")
async def liveness() -> HealthResponse:
    return HealthResponse(status="ok")


@health_router.get("/ready", response_model=ReadinessResponse, operation_id="healthReady")
async def readiness() -> ReadinessResponse:
    started = time.perf_counter()
    registry_status = "error"
    database_status = "error"
    try:
        pool = await get_pool_for_tenant(settings, settings.READINESS_TENANT_ID, strict=True)
        registry_status = "ok"
        await pool.fetchval("SELECT 1")
        schema_query, required_tables = _SCHEMA_CHECKS[settings.DB_ENGINE]
        table_count = await pool.fetchval(schema_query, *required_tables)
        if int(table_count or 0) != len(required_tables):
            database_status = "schema_missing"
            raise RuntimeError("Required portfolio tables are not materialized")
        database_status = "ok"
    except Exception as exc:
        logger.error("readiness_dependency_failed type=%s", type(exc).__name__)
    latency = round((time.perf_counter() - started) * 1000, 2)
    payload = ReadinessResponse(
        status="ok" if database_status == "ok" else "not_ready",
        tenant_registry=registry_status,
        tenant_database=database_status,
        latency_ms=latency,
    )
    if payload.status != "ok":
        raise HTTPException(status_code=503, detail=payload.model_dump())
    return payload
