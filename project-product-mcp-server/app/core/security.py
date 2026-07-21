"""Authentication, tenant binding and explicit portfolio role policy."""

from __future__ import annotations

import secrets
from collections.abc import Callable
from typing import Any, Literal

from fastapi import Depends, Header, HTTPException, Request
from platform_auth.jwt_manager import decode_token, jwt_manager
from platform_core.request_context import get_tenant_id

from app.core.config import settings


def bind_authenticated_claims(
    request: Request,
    raw_token: str = Depends(jwt_manager),
) -> dict[str, Any]:
    """Decode the token already verified by ``jwt_manager`` and bind its tenant.

    ``jwt_manager`` intentionally returns the raw bearer token, not its claims.  The
    browser access-token contract currently carries ``sub``, ``tenant_id``, ``role``
    and ``roles``; it does not carry invented per-service ``scopes``.
    """
    claims = decode_token(raw_token)
    if claims.get("type") != "access":
        raise HTTPException(status_code=401, detail="A user access token is required")
    trusted_tenant = get_tenant_id()
    claim_tenant = claims.get(settings.TENANT_JWT_CLAIM)
    if not isinstance(trusted_tenant, str) or not trusted_tenant:
        raise HTTPException(status_code=400, detail="Missing trusted tenant context")
    if claim_tenant is None or str(claim_tenant).strip() != trusted_tenant:
        raise HTTPException(status_code=403, detail="Tenant context does not match token")
    request.state.jwt_claims = claims
    return claims


PortfolioAccess = Literal["read", "write", "delete"]

_PORTFOLIO_ROLES: dict[PortfolioAccess, frozenset[str]] = {
    "read": frozenset({"VIEWER", "EDITOR", "ADMIN", "SUPERADMIN"}),
    "write": frozenset({"EDITOR", "ADMIN", "SUPERADMIN"}),
    "delete": frozenset({"ADMIN", "SUPERADMIN"}),
}


def _token_roles(claims: dict[str, Any]) -> frozenset[str]:
    values: list[str] = []
    role = claims.get("role")
    if isinstance(role, str) and role.strip():
        values.append(role)
    roles = claims.get("roles")
    if isinstance(roles, list):
        values.extend(item for item in roles if isinstance(item, str) and item.strip())
    return frozenset(value.strip().upper() for value in values)


def require_portfolio_access(access: PortfolioAccess) -> Callable[..., dict[str, Any]]:
    """Authorize a portfolio action against the roles emitted by platform-auth.

    Missing, malformed and unknown roles always deny.  There is no wildcard and no
    implicit elevation from a token shape that the issuer does not provide.
    """
    allowed = _PORTFOLIO_ROLES[access]

    def dependency(request: Request) -> dict[str, Any]:
        claims = getattr(request.state, "jwt_claims", None)
        if not isinstance(claims, dict):
            raise HTTPException(status_code=401, detail="Missing authenticated claims")
        if not (_token_roles(claims) & allowed):
            raise HTTPException(status_code=403, detail="Role is not authorized for this action")
        return claims

    return dependency


def require_internal_token(
    token: str | None = Header(default=None, alias="X-Internal-Token"),
) -> None:
    configured = settings.INTERNAL_API_TOKEN
    if configured is None:
        raise HTTPException(status_code=503, detail="Internal authentication unavailable")
    expected = configured.get_secret_value()
    if not token or not secrets.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail="Invalid internal service credential")
