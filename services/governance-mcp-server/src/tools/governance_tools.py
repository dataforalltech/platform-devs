"""Governance tools for platform-governance-mcp."""

import json
import logging
from typing import Any

from mcp.types import TextContent

from ..client.api_client import GovernanceApiClient
from ..config.settings import Settings

logger = logging.getLogger(__name__)

# Lazy singleton pattern for test monkeypatching
_settings: Settings | None = None
_api_client: GovernanceApiClient | None = None

# Module-level None sentinel for test monkeypatching
api_client: GovernanceApiClient | None = None
settings: Settings | None = None


def _get_settings() -> Settings:
    """Get or create settings singleton."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def _get_api_client() -> GovernanceApiClient:
    """Get or create API client singleton."""
    global _api_client
    if _api_client is None:
        _api_client = GovernanceApiClient(_get_settings())
    return _api_client


async def governance_health_check() -> list[TextContent]:
    """Check if platform-governance service is healthy.

    Returns:
        List containing status response as JSON.
    """
    client = api_client if api_client is not None else _get_api_client()
    try:
        response = await client.get("/api/health")
        if response.status_code == 200:
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "status": "ok",
                            "data": response.json(),
                        }
                    ),
                )
            ]
        else:
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "error": "HealthCheckFailed",
                            "details": f"Status {response.status_code}",
                        }
                    ),
                )
            ]
    except Exception as e:
        logger.exception("Error checking health")
        return [
            TextContent(
                type="text",
                text=json.dumps({"error": "InternalError", "details": str(e)}),
            )
        ]


async def governance_get_policy(policy_id: str) -> list[TextContent]:
    """Get a specific policy by ID.

    Args:
        policy_id: The policy ID to retrieve.

    Returns:
        List containing policy details.
    """
    client = api_client if api_client is not None else _get_api_client()
    try:
        response = await client.get(f"/api/v1/policies/{policy_id}")
        if response.status_code == 200:
            return [TextContent(type="text", text=json.dumps(response.json()))]
        elif response.status_code == 404:
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "error": "PolicyNotFound",
                            "details": f"Policy {policy_id} not found",
                        }
                    ),
                )
            ]
        else:
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "error": "GetPolicyFailed",
                            "details": f"Status {response.status_code}",
                        }
                    ),
                )
            ]
    except Exception as e:
        logger.exception("Error getting policy")
        return [
            TextContent(
                type="text",
                text=json.dumps({"error": "InternalError", "details": str(e)}),
            )
        ]


async def governance_list_policies() -> list[TextContent]:
    """List all available policies.

    Returns:
        List containing policies.
    """
    client = api_client if api_client is not None else _get_api_client()
    try:
        response = await client.get("/api/v1/policies")
        if response.status_code == 200:
            return [TextContent(type="text", text=json.dumps(response.json()))]
        else:
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "error": "ListPoliciesFailed",
                            "details": f"Status {response.status_code}",
                        }
                    ),
                )
            ]
    except Exception as e:
        logger.exception("Error listing policies")
        return [
            TextContent(
                type="text",
                text=json.dumps({"error": "InternalError", "details": str(e)}),
            )
        ]


async def governance_check_access(
    user_id: str, resource: str, action: str
) -> list[TextContent]:
    """Check if a user has access to perform an action on a resource.

    Args:
        user_id: The user ID to check.
        resource: The resource being accessed.
        action: The action being performed.

    Returns:
        List containing access check result.
    """
    client = api_client if api_client is not None else _get_api_client()
    try:
        payload: dict[str, Any] = {
            "user_id": user_id,
            "resource": resource,
            "action": action,
        }
        response = await client.post("/api/v1/check-access", json=payload)
        if response.status_code == 200:
            return [TextContent(type="text", text=json.dumps(response.json()))]
        else:
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "error": "CheckAccessFailed",
                            "details": f"Status {response.status_code}",
                        }
                    ),
                )
            ]
    except Exception as e:
        logger.exception("Error checking access")
        return [
            TextContent(
                type="text",
                text=json.dumps({"error": "InternalError", "details": str(e)}),
            )
        ]


async def governance_list_permissions() -> list[TextContent]:
    """List all available permissions.

    Returns:
        List containing permissions.
    """
    client = api_client if api_client is not None else _get_api_client()
    try:
        response = await client.get("/api/v1/permissions")
        if response.status_code == 200:
            return [TextContent(type="text", text=json.dumps(response.json()))]
        else:
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "error": "ListPermissionsFailed",
                            "details": f"Status {response.status_code}",
                        }
                    ),
                )
            ]
    except Exception as e:
        logger.exception("Error listing permissions")
        return [
            TextContent(
                type="text",
                text=json.dumps({"error": "InternalError", "details": str(e)}),
            )
        ]


async def governance_get_user_permissions(user_id: str) -> list[TextContent]:
    """Get all permissions for a specific user.

    Args:
        user_id: The user ID to get permissions for.

    Returns:
        List containing user permissions.
    """
    client = api_client if api_client is not None else _get_api_client()
    try:
        response = await client.get(f"/api/v1/users/{user_id}/permissions")
        if response.status_code == 200:
            return [TextContent(type="text", text=json.dumps(response.json()))]
        elif response.status_code == 404:
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "error": "UserNotFound",
                            "details": f"User {user_id} not found",
                        }
                    ),
                )
            ]
        else:
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "error": "GetUserPermissionsFailed",
                            "details": f"Status {response.status_code}",
                        }
                    ),
                )
            ]
    except Exception as e:
        logger.exception("Error getting user permissions")
        return [
            TextContent(
                type="text",
                text=json.dumps({"error": "InternalError", "details": str(e)}),
            )
        ]


async def governance_update_rls(resource: str, rules: dict[str, Any]) -> list[TextContent]:
    """Update row-level security rules for a resource.

    Args:
        resource: The resource name.
        rules: Dictionary containing the RLS rules.

    Returns:
        List containing update result.
    """
    client = api_client if api_client is not None else _get_api_client()
    try:
        payload: dict[str, Any] = {
            "resource": resource,
            "rules": rules,
        }
        response = await client.post("/api/v1/rls", json=payload)
        if response.status_code == 200:
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "status": "ok",
                            "message": f"RLS rules updated for {resource}",
                            "data": response.json(),
                        }
                    ),
                )
            ]
        else:
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "error": "UpdateRLSFailed",
                            "details": f"Status {response.status_code}",
                        }
                    ),
                )
            ]
    except Exception as e:
        logger.exception("Error updating RLS")
        return [
            TextContent(
                type="text",
                text=json.dumps({"error": "InternalError", "details": str(e)}),
            )
        ]


async def governance_get_rls(resource: str) -> list[TextContent]:
    """Get row-level security rules for a resource.

    Args:
        resource: The resource name to get RLS rules for.

    Returns:
        List containing RLS rules.
    """
    client = api_client if api_client is not None else _get_api_client()
    try:
        response = await client.get(f"/api/v1/rls/{resource}")
        if response.status_code == 200:
            return [TextContent(type="text", text=json.dumps(response.json()))]
        elif response.status_code == 404:
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "error": "RLSNotFound",
                            "details": f"RLS rules for {resource} not found",
                        }
                    ),
                )
            ]
        else:
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "error": "GetRLSFailed",
                            "details": f"Status {response.status_code}",
                        }
                    ),
                )
            ]
    except Exception as e:
        logger.exception("Error getting RLS")
        return [
            TextContent(
                type="text",
                text=json.dumps({"error": "InternalError", "details": str(e)}),
            )
        ]
