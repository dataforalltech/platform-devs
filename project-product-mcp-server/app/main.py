"""Trinity API runtime; migrations are intentionally an isolated release job."""

from __future__ import annotations

import asyncio
import logging
import secrets
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from platform_core.exceptions import DomainError, IntegrationClientError
from platform_core.logging import RequestLoggingMiddleware, configure_logging
from platform_database import get_pool
from platform_observability.limiter import rate_limit_exceeded_handler
from platform_observability.otel import instrument_fastapi, setup_otel
from platform_observability.security_headers import (
    RequestSizeLimitMiddleware,
    SecurityHeadersMiddleware,
)
from platform_observability.sentry import setup_sentry
from platform_tenant.middleware import TenantMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.responses import JSONResponse

from app.api import api_router
from app.api.health import health_router
from app.core.config import settings
from app.core.database import close_database, configure_database
from app.core.exceptions import (
    domain_exception_handler,
    generic_exception_handler,
    http_exception_handler,
    integration_exception_handler,
    validation_exception_handler,
)
from app.core.limiter import limiter

configure_logging(log_level=settings.LOG_LEVEL, temp_folder=settings.LOG_TEMP_FOLDER)
logger = logging.getLogger(__name__)

setup_otel(settings)
setup_sentry(settings)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    configure_database()
    logger.info(
        "service_started name=%s environment=%s",
        settings.APP_NAME,
        settings.ENVIRONMENT,
    )
    try:
        yield
    finally:
        await close_database()
        logger.info("service_stopped name=%s", settings.APP_NAME)


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    root_path=settings.ROOT_PATH,
    lifespan=lifespan,
)
management_app = FastAPI(
    title=f"{settings.APP_NAME}-management",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
management_app.include_router(health_router)


@management_app.middleware("http")
async def protect_metrics(request: Request, call_next):
    if request.url.path != "/metrics":
        return await call_next(request)

    authorization = request.headers.get("authorization", "")
    scheme, separator, provided = authorization.partition(" ")
    configured = settings.METRICS_SCRAPE_TOKEN
    expected = configured.get_secret_value() if configured else ""
    valid = (
        separator == " "
        and scheme.lower() == "bearer"
        and bool(provided)
        and bool(expected)
        and secrets.compare_digest(provided, expected)
    )
    if not valid:
        return JSONResponse(
            status_code=401,
            content={
                "error": "METRICS_UNAUTHORIZED",
                "message": "Valid scraper credential required",
                "detail": {},
                "request_id": request.headers.get("X-Correlation-Id", ""),
            },
            headers={"WWW-Authenticate": "Bearer"},
        )
    return await call_next(request)


app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

instrument_fastapi(app, settings)
if settings.METRICS_ENABLED:
    from prometheus_fastapi_instrumentator import Instrumentator

    Instrumentator().instrument(app).expose(
        management_app,
        endpoint="/metrics",
        include_in_schema=False,
    )

# Middleware registration is inverse to the effective outer-to-inner order.
app.add_middleware(
    RequestLoggingMiddleware,
    temp_folder=settings.LOG_TEMP_FOLDER,
)
app.add_middleware(
    TenantMiddleware,
    tenant_jwt_claim=settings.TENANT_JWT_CLAIM,
    get_pool=get_pool,
    settings=settings,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "X-Correlation-Id",
    ],
)
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(SecurityHeadersMiddleware, environment=settings.ENVIRONMENT)
app.add_middleware(
    RequestSizeLimitMiddleware,
    max_bytes=settings.MAX_REQUEST_SIZE_BYTES,
)

app.add_exception_handler(DomainError, domain_exception_handler)
app.add_exception_handler(IntegrationClientError, integration_exception_handler)
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, generic_exception_handler)
app.include_router(api_router)


async def serve() -> None:
    import uvicorn

    api_server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="0.0.0.0",
            port=settings.API_PORT,
            log_level=settings.LOG_LEVEL.lower(),
            access_log=False,
        )
    )
    management_server = uvicorn.Server(
        uvicorn.Config(
            management_app,
            host="0.0.0.0",
            port=settings.HEALTH_PORT,
            log_level=settings.LOG_LEVEL.lower(),
            access_log=False,
        )
    )
    await asyncio.gather(api_server.serve(), management_server.serve())


def main() -> None:
    asyncio.run(serve())


if __name__ == "__main__":
    main()
