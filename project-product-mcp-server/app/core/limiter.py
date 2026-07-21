"""Shared API rate limiter configured by the observability library."""

from platform_observability.limiter import build_limiter

from app.core.config import settings

limiter = build_limiter(settings)
