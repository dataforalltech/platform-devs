"""Build and sign trustworthy downstream execution context."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import uuid
from dataclasses import dataclass, replace
from typing import Any

from src.auth.token_validator import UserSession


class ContextConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class ExecutionContext:
    actor_id: str
    actor_type: str
    tenant_id: str
    roles: list[str]
    scopes: list[str]
    environment: str
    correlation_id: str
    causation_id: str
    session_id: str | None
    issued_at: int
    policy_decision_id: str | None = None
    approval_ids: list[str] | None = None

    def with_policy(self, decision_id: str, approvals: list[str]) -> "ExecutionContext":
        return replace(self, policy_decision_id=decision_id, approval_ids=approvals)

    def payload(self) -> dict[str, Any]:
        return {
            "actor_id": self.actor_id,
            "actor_type": self.actor_type,
            "tenant_id": self.tenant_id,
            "roles": self.roles,
            "scopes": self.scopes,
            "environment": self.environment,
            "correlation_id": self.correlation_id,
            "causation_id": self.causation_id,
            "session_id": self.session_id,
            "issued_at": self.issued_at,
            "policy_decision_id": self.policy_decision_id,
            "approval_ids": self.approval_ids or [],
        }


def build_context(
    user: UserSession,
    *,
    correlation_id: str | None,
    causation_id: str | None,
    session_id: str | None,
) -> ExecutionContext:
    if not user.tenant_id:
        raise ValueError("verified tenant is required")
    correlation = correlation_id or str(uuid.uuid4())
    return ExecutionContext(
        actor_id=user.user_id,
        actor_type=user.actor_type,
        tenant_id=user.tenant_id,
        roles=[user.role],
        scopes=sorted(set(user.scopes)),
        environment=os.environ.get("GATEWAY_ENVIRONMENT", "local"),
        correlation_id=correlation,
        causation_id=causation_id or correlation,
        session_id=session_id,
        issued_at=int(time.time()),
    )


def sign_context(context: ExecutionContext) -> tuple[str, str]:
    key = os.environ.get("GATEWAY_CONTEXT_SIGNING_KEY")
    if not key:
        raise ContextConfigurationError("GATEWAY_CONTEXT_SIGNING_KEY is required")
    raw = json.dumps(context.payload(), sort_keys=True, separators=(",", ":")).encode()
    encoded = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    signature = hmac.new(key.encode(), encoded.encode(), hashlib.sha256).hexdigest()
    return encoded, signature
