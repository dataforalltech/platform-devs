"""Fail-closed client for the external policy decision point (PDP)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx

from src.security.context import ExecutionContext


class PolicyUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class PolicyDecision:
    decision_id: str
    allowed: bool
    approval_ids: list[str]
    reason: str | None = None


class PolicyClient:
    async def authorize(
        self,
        *,
        context: ExecutionContext,
        provider: str,
        tool: str,
        arguments: dict[str, Any],
        requested_approval_ids: list[str],
        local_policy: dict[str, Any] | None,
    ) -> PolicyDecision:
        base_url = os.environ.get("GATEWAY_PDP_URL")
        if not base_url:
            raise PolicyUnavailable("GATEWAY_PDP_URL is required")
        body = {
            "context": context.payload(),
            "resource": {"provider": provider, "tool": tool},
            "arguments": arguments,
            "requested_approval_ids": requested_approval_ids,
            "contract": local_policy or {},
        }
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.post(f"{base_url.rstrip('/')}/v1/decisions", json=body)
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise PolicyUnavailable("policy decision point unavailable") from exc
        decision_id = payload.get("decision_id")
        allowed = payload.get("allowed")
        approvals = payload.get("approval_ids", [])
        if not isinstance(decision_id, str) or not isinstance(allowed, bool) or not isinstance(approvals, list):
            raise PolicyUnavailable("invalid PDP response")
        return PolicyDecision(
            decision_id=decision_id,
            allowed=allowed,
            approval_ids=[str(item) for item in approvals],
            reason=payload.get("reason"),
        )


policy_client = PolicyClient()
