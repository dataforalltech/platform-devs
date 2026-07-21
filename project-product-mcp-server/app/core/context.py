"""Validated audit actor with a server-owned tenant-global portfolio scope."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import Header, HTTPException, Request

TENANT_GLOBAL_SCOPE_ID = 0


@dataclass(frozen=True)
class ActorContext:
    actor_id: int
    environment_id: int
    request_id: str | None

    def __post_init__(self) -> None:
        if self.environment_id != TENANT_GLOBAL_SCOPE_ID:
            raise ValueError("Portfolio environment scope is tenant-global and server-owned")

    @property
    def owner_id(self) -> int:
        """Portfolio rows are shared by the tenant; actor identity remains audit-only."""
        return TENANT_GLOBAL_SCOPE_ID


def _positive_actor(raw: Any) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="Invalid actor subject") from exc
    if value <= 0:
        raise HTTPException(status_code=401, detail="Invalid actor subject")
    return value


def public_actor_context(request: Request) -> ActorContext:
    claims = getattr(request.state, "jwt_claims", None)
    if not isinstance(claims, dict):
        raise HTTPException(status_code=401, detail="Missing authenticated claims")
    actor_id = _positive_actor(claims.get("sub"))
    return ActorContext(
        actor_id,
        TENANT_GLOBAL_SCOPE_ID,
        getattr(request.state, "request_id", None),
    )


def internal_actor_context(
    request: Request,
    actor_id: str | None = Header(default=None, alias="X-Actor-Id"),
) -> ActorContext:
    return ActorContext(
        _positive_actor(actor_id),
        TENANT_GLOBAL_SCOPE_ID,
        getattr(request.state, "request_id", None),
    )
