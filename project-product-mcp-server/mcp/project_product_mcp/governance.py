"""Fail-closed policy adapter for platform-governance."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Literal

import httpx

from .config.settings import Settings


@dataclass(frozen=True)
class GovernanceDecision:
    outcome: Literal["allow", "deny", "pending"]
    approval_uid: str | None = None
    checkpoint_uid: str | None = None


class GovernancePolicyEnforcementPoint:
    def __init__(self, settings: Settings) -> None:
        token = settings.GOVERNANCE_INTERNAL_TOKEN
        if token is None or not token.get_secret_value():
            raise RuntimeError("governance credential was not resolved")
        self._client = httpx.AsyncClient(
            base_url=settings.GOVERNANCE_BASE_URL.rstrip("/"),
            headers={
                "X-Internal-Token": token.get_secret_value(),
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=settings.MCP_REQUEST_TIMEOUT_SECONDS,
            follow_redirects=False,
            trust_env=False,
        )

    @staticmethod
    def _subject(claims: dict[str, Any]) -> dict[str, Any]:
        # Governance evaluates the human principal's tenant/environment role
        # bindings while retaining ``type=agent`` for executor-class policy. The
        # delegated agent id remains available in the signed ``act`` claim and is
        # forwarded in the evaluation context below.
        return {
            "type": "agent",
            "id": str(claims["sub"]),
            "profile": None,
            "teams": [],
            "domain": "portfolio",
        }

    @staticmethod
    def _resource_id(arguments: dict[str, Any]) -> str | None:
        for key in ("binding_id", "project_id", "product_id"):
            value = arguments.get(key)
            if value is not None:
                return str(value)
        return None

    async def evaluate(
        self,
        *,
        tool_name: str,
        metadata: dict[str, Any],
        claims: dict[str, Any],
        arguments: dict[str, Any],
    ) -> GovernanceDecision:
        payload = {
            "subject": self._subject(claims),
            "action_class": metadata["capability"],
            "resource_type": metadata["resource_type"],
            "resource_id": self._resource_id(arguments),
            "tenant_id": claims["tenant_id"],
            "environment_id": claims["_environment_id"],
            "context": {
                "tool_name": tool_name,
                "required_scope": metadata["required_scope"],
                "data_domain": metadata["data_domain"],
                "jti": claims["jti"],
                "agent_id": (
                    claims.get("act", {}).get("sub")
                    if isinstance(claims.get("act"), dict)
                    else None
                ),
            },
        }
        response = await self._client.post(
            "/api/v1/internal/action-classes/evaluate",
            json=payload,
            headers={"X-Tenant-Id": claims["tenant_id"]},
        )
        response.raise_for_status()
        decision = response.json()
        if decision.get("decision") == "allow" and decision.get("allowed") is True:
            return GovernanceDecision("allow")
        if decision.get("decision") != "pending_approval":
            return GovernanceDecision("deny")

        canonical = json.dumps(arguments, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        idem = str(
            arguments.get("idempotency_key")
            or hashlib.sha256(f"{claims['jti']}:{tool_name}:{canonical}".encode()).hexdigest()
        )
        pending_payload = {
            "ownerService": "platform-project-product",
            "capability": metadata["capability"],
            "actionPayload": {"tool": tool_name, "arguments": arguments},
            "idempotencyKey": idem,
            "twinContext": {
                "sub": str(claims["sub"]),
                "twinId": claims.get("twin_id"),
                "tenantId": claims["tenant_id"],
                "scopes": claims.get("scopes", []),
                "jti": claims["jti"],
            },
            "correlationId": claims.get("parent_jti"),
            "principalUserId": str(claims["sub"]),
            "dataDomainId": metadata["data_domain"],
            "agentDefinitionUid": claims.get("twin_id"),
            "actionSummary": {
                "tool": tool_name,
                "resourceType": metadata["resource_type"],
                "resourceId": self._resource_id(arguments),
            },
        }
        parked = await self._client.post(
            "/api/v1/internal/twin-runtime/pending",
            json=pending_payload,
            headers={"X-Tenant-Id": claims["tenant_id"]},
        )
        parked.raise_for_status()
        body = parked.json()
        approval_uid = body.get("approvalUid") or body.get("approval_uid")
        checkpoint_uid = body.get("checkpointUid") or body.get("checkpoint_uid")
        if not approval_uid or not checkpoint_uid:
            raise RuntimeError("governance returned an invalid pending contract")
        return GovernanceDecision("pending", str(approval_uid), str(checkpoint_uid))

    async def readiness(self) -> None:
        """Require governance's dependency-aware readiness, not process liveness."""
        response = await self._client.get("/api/health/ready")
        if not response.is_success:
            raise RuntimeError("governance readiness check failed")

    async def aclose(self) -> None:
        await self._client.aclose()
