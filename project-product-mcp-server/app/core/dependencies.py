"""Bind the trusted tenant ContextVar to canonical ORM repositories."""

from __future__ import annotations

from fastapi import HTTPException
from platform_core.request_context import get_tenant_id

from app.core.repositories import portfolio_repositories


async def get_portfolio_repositories():
    tenant_id = get_tenant_id()
    if not isinstance(tenant_id, str) or not tenant_id:
        raise HTTPException(status_code=400, detail="Missing trusted tenant context")
    async with portfolio_repositories(tenant_id) as repositories:
        yield repositories
