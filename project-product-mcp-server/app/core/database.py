"""Credential-zero adapter for the canonical platform ORM."""

from platform_database import close_tenant_pools
from platform_database.orm import configure, for_tenant

from app.core.config import settings


def configure_database() -> None:
    """Register the PLATFORMS resolver once; no tenant credential is accepted here."""
    configure(settings)


async def close_database() -> None:
    await close_tenant_pools()


__all__ = ["close_database", "configure_database", "for_tenant"]
