"""Admin tools for platform-admin-mcp."""

import json
import logging
from typing import Any

from mcp.types import TextContent

from ..client.api_client import AdminApiClient
from ..config.settings import Settings

logger = logging.getLogger(__name__)

# Lazy singleton pattern for test monkeypatching
_settings: Settings | None = None
_api_client: AdminApiClient | None = None

# Module-level None sentinel for test monkeypatching
api_client: AdminApiClient | None = None
settings: Settings | None = None


def _get_settings() -> Settings:
    """Get or create settings singleton."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def _get_api_client() -> AdminApiClient:
    """Get or create API client singleton."""
    global _api_client
    if _api_client is None:
        _api_client = AdminApiClient(_get_settings())
    return _api_client


async def admin_health_check() -> list[TextContent]:
    """Check if platform-admin service is healthy.

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


async def admin_list_users() -> list[TextContent]:
    """List all users in the system.

    Returns:
        List containing users data.
    """
    client = api_client if api_client is not None else _get_api_client()
    try:
        response = await client.get("/api/v1/users")
        if response.status_code == 200:
            return [TextContent(type="text", text=json.dumps(response.json()))]
        else:
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "error": "ListUsersFailed",
                            "details": f"Status {response.status_code}",
                        }
                    ),
                )
            ]
    except Exception as e:
        logger.exception("Error listing users")
        return [
            TextContent(
                type="text",
                text=json.dumps({"error": "InternalError", "details": str(e)}),
            )
        ]


async def admin_get_user(user_id: str) -> list[TextContent]:
    """Get details of a specific user.

    Args:
        user_id: The user ID.

    Returns:
        List containing user information.
    """
    client = api_client if api_client is not None else _get_api_client()
    try:
        response = await client.get(f"/api/v1/users/{user_id}")
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
                            "error": "GetUserFailed",
                            "details": f"Status {response.status_code}",
                        }
                    ),
                )
            ]
    except Exception as e:
        logger.exception("Error getting user")
        return [
            TextContent(
                type="text",
                text=json.dumps({"error": "InternalError", "details": str(e)}),
            )
        ]


async def admin_create_user(
    email: str,
    name: str,
    domain_id: str | None = None,
) -> list[TextContent]:
    """Create a new user.

    Args:
        email: User email address.
        name: User full name.
        domain_id: Optional domain ID.

    Returns:
        List containing created user information.
    """
    client = api_client if api_client is not None else _get_api_client()
    try:
        payload: dict[str, Any] = {"email": email, "name": name}
        if domain_id:
            payload["domain_id"] = domain_id

        response = await client.post("/api/v1/users", json=payload)
        if response.status_code == 201:
            return [TextContent(type="text", text=json.dumps(response.json()))]
        else:
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "error": "CreateUserFailed",
                            "details": f"Status {response.status_code}",
                        }
                    ),
                )
            ]
    except Exception as e:
        logger.exception("Error creating user")
        return [
            TextContent(
                type="text",
                text=json.dumps({"error": "InternalError", "details": str(e)}),
            )
        ]


async def admin_list_domains() -> list[TextContent]:
    """List all domains in the system.

    Returns:
        List containing domains data.
    """
    client = api_client if api_client is not None else _get_api_client()
    try:
        response = await client.get("/api/v1/domains")
        if response.status_code == 200:
            return [TextContent(type="text", text=json.dumps(response.json()))]
        else:
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "error": "ListDomainsFailed",
                            "details": f"Status {response.status_code}",
                        }
                    ),
                )
            ]
    except Exception as e:
        logger.exception("Error listing domains")
        return [
            TextContent(
                type="text",
                text=json.dumps({"error": "InternalError", "details": str(e)}),
            )
        ]


async def admin_list_tenants() -> list[TextContent]:
    """List all tenants in the system.

    Returns:
        List containing tenants data.
    """
    client = api_client if api_client is not None else _get_api_client()
    try:
        response = await client.get("/api/v1/tenants")
        if response.status_code == 200:
            return [TextContent(type="text", text=json.dumps(response.json()))]
        else:
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "error": "ListTenantsFailed",
                            "details": f"Status {response.status_code}",
                        }
                    ),
                )
            ]
    except Exception as e:
        logger.exception("Error listing tenants")
        return [
            TextContent(
                type="text",
                text=json.dumps({"error": "InternalError", "details": str(e)}),
            )
        ]


async def admin_get_tenant(tenant_id: str) -> list[TextContent]:
    """Get details of a specific tenant.

    Args:
        tenant_id: The tenant ID.

    Returns:
        List containing tenant information.
    """
    client = api_client if api_client is not None else _get_api_client()
    try:
        response = await client.get(f"/api/v1/tenants/{tenant_id}")
        if response.status_code == 200:
            return [TextContent(type="text", text=json.dumps(response.json()))]
        elif response.status_code == 404:
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "error": "TenantNotFound",
                            "details": f"Tenant {tenant_id} not found",
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
                            "error": "GetTenantFailed",
                            "details": f"Status {response.status_code}",
                        }
                    ),
                )
            ]
    except Exception as e:
        logger.exception("Error getting tenant")
        return [
            TextContent(
                type="text",
                text=json.dumps({"error": "InternalError", "details": str(e)}),
            )
        ]


async def admin_assign_role(
    user_id: str,
    role_id: str,
) -> list[TextContent]:
    """Assign a role to a user.

    Args:
        user_id: The user ID.
        role_id: The role ID to assign.

    Returns:
        List containing assignment result.
    """
    client = api_client if api_client is not None else _get_api_client()
    try:
        response = await client.post(
            f"/api/v1/users/{user_id}/roles",
            json={"role_id": role_id},
        )
        if response.status_code == 200:
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "status": "ok",
                            "message": "Role assigned successfully",
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
                            "error": "AssignRoleFailed",
                            "details": f"Status {response.status_code}",
                        }
                    ),
                )
            ]
    except Exception as e:
        logger.exception("Error assigning role")
        return [
            TextContent(
                type="text",
                text=json.dumps({"error": "InternalError", "details": str(e)}),
            )
        ]


async def admin_list_roles() -> list[TextContent]:
    """List all available roles.

    Returns:
        List containing roles data.
    """
    client = api_client if api_client is not None else _get_api_client()
    try:
        response = await client.get("/api/v1/roles")
        if response.status_code == 200:
            return [TextContent(type="text", text=json.dumps(response.json()))]
        else:
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "error": "ListRolesFailed",
                            "details": f"Status {response.status_code}",
                        }
                    ),
                )
            ]
    except Exception as e:
        logger.exception("Error listing roles")
        return [
            TextContent(
                type="text",
                text=json.dumps({"error": "InternalError", "details": str(e)}),
            )
        ]
