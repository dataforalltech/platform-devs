"""Authentication tools for platform-auth-mcp."""

import json
import logging
from typing import Any

from mcp.types import TextContent

from ..client.api_client import AuthApiClient
from ..config.settings import Settings

logger = logging.getLogger(__name__)

# Lazy singleton pattern for test monkeypatching
_settings: Settings | None = None
_api_client: AuthApiClient | None = None

# Module-level None sentinel for test monkeypatching
api_client: AuthApiClient | None = None
settings: Settings | None = None


def _get_settings() -> Settings:
    """Get or create settings singleton."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def _get_api_client() -> AuthApiClient:
    """Get or create API client singleton."""
    global _api_client
    if _api_client is None:
        _api_client = AuthApiClient(_get_settings())
    return _api_client


async def auth_health_check() -> list[TextContent]:
    """Check if platform-auth service is healthy.

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


async def auth_check_email(email: str) -> list[TextContent]:
    """Determine authentication type for an email (SSO or password).

    Args:
        email: User email address.

    Returns:
        List containing auth type info.
    """
    client = api_client if api_client is not None else _get_api_client()
    try:
        response = await client.post("/api/v1/auth/check-email", json={"email": email})
        if response.status_code == 200:
            return [TextContent(type="text", text=json.dumps(response.json()))]
        else:
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "error": "CheckEmailFailed",
                            "details": f"Status {response.status_code}",
                        }
                    ),
                )
            ]
    except Exception as e:
        logger.exception("Error checking email")
        return [
            TextContent(
                type="text",
                text=json.dumps({"error": "InternalError", "details": str(e)}),
            )
        ]


async def auth_list_tenants() -> list[TextContent]:
    """List available tenants for login selector.

    Returns:
        List containing tenant information.
    """
    client = api_client if api_client is not None else _get_api_client()
    try:
        response = await client.get("/api/v1/auth/tenants")
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


async def auth_login(email: str, password: str, tenant_id: str | None = None) -> list[TextContent]:
    """Authenticate user with email and password.

    Args:
        email: User email.
        password: User password.
        tenant_id: Optional tenant ID.

    Returns:
        List containing tokens and user info.
    """
    client = api_client if api_client is not None else _get_api_client()
    try:
        payload: dict[str, Any] = {"email": email, "password": password}
        if tenant_id:
            payload["tenant_id"] = tenant_id

        response = await client.post("/api/v1/auth/login", json=payload)
        if response.status_code == 200:
            return [TextContent(type="text", text=json.dumps(response.json()))]
        else:
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "error": "LoginFailed",
                            "details": f"Status {response.status_code}",
                        }
                    ),
                )
            ]
    except Exception as e:
        logger.exception("Error during login")
        return [
            TextContent(
                type="text",
                text=json.dumps({"error": "InternalError", "details": str(e)}),
            )
        ]


async def auth_get_me(authorization: str) -> list[TextContent]:
    """Get current authenticated user info.

    Args:
        authorization: Bearer token from Authorization header.

    Returns:
        List containing user information.
    """
    client = api_client if api_client is not None else _get_api_client()
    try:
        headers = {"Authorization": authorization}
        response = await client.get("/api/v1/auth/me", headers=headers)
        if response.status_code == 200:
            return [TextContent(type="text", text=json.dumps(response.json()))]
        elif response.status_code == 401:
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "error": "Unauthorized",
                            "details": "Invalid or expired token",
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
                            "error": "GetMeFailed",
                            "details": f"Status {response.status_code}",
                        }
                    ),
                )
            ]
    except Exception as e:
        logger.exception("Error getting user info")
        return [
            TextContent(
                type="text",
                text=json.dumps({"error": "InternalError", "details": str(e)}),
            )
        ]


async def auth_get_permissions(authorization: str) -> list[TextContent]:
    """Get current user's permissions and access profile.

    Args:
        authorization: Bearer token from Authorization header.

    Returns:
        List containing permission information.
    """
    client = api_client if api_client is not None else _get_api_client()
    try:
        headers = {"Authorization": authorization}
        response = await client.get("/api/v1/auth/me/permissions", headers=headers)
        if response.status_code == 200:
            return [TextContent(type="text", text=json.dumps(response.json()))]
        elif response.status_code == 401:
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "error": "Unauthorized",
                            "details": "Invalid or expired token",
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
                            "error": "GetPermissionsFailed",
                            "details": f"Status {response.status_code}",
                        }
                    ),
                )
            ]
    except Exception as e:
        logger.exception("Error getting permissions")
        return [
            TextContent(
                type="text",
                text=json.dumps({"error": "InternalError", "details": str(e)}),
            )
        ]


async def auth_refresh_token(refresh_token: str) -> list[TextContent]:
    """Refresh access token using refresh token.

    Args:
        refresh_token: The refresh token.

    Returns:
        List containing new access token.
    """
    client = api_client if api_client is not None else _get_api_client()
    try:
        response = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": refresh_token},
        )
        if response.status_code == 200:
            return [TextContent(type="text", text=json.dumps(response.json()))]
        else:
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "error": "RefreshTokenFailed",
                            "details": f"Status {response.status_code}",
                        }
                    ),
                )
            ]
    except Exception as e:
        logger.exception("Error refreshing token")
        return [
            TextContent(
                type="text",
                text=json.dumps({"error": "InternalError", "details": str(e)}),
            )
        ]


async def auth_logout(refresh_token: str) -> list[TextContent]:
    """Revoke refresh token and logout user.

    Args:
        refresh_token: The refresh token to revoke.

    Returns:
        List containing logout confirmation.
    """
    client = api_client if api_client is not None else _get_api_client()
    try:
        response = await client.post(
            "/api/v1/auth/logout",
            json={"refresh_token": refresh_token},
        )
        if response.status_code == 200:
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "status": "ok",
                            "message": "Successfully logged out",
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
                            "error": "LogoutFailed",
                            "details": f"Status {response.status_code}",
                        }
                    ),
                )
            ]
    except Exception as e:
        logger.exception("Error during logout")
        return [
            TextContent(
                type="text",
                text=json.dumps({"error": "InternalError", "details": str(e)}),
            )
        ]


async def auth_get_service_token(service_id: str, service_secret: str) -> list[TextContent]:
    """Get service-to-service authentication token.

    Args:
        service_id: Service identifier.
        service_secret: Service secret/password.

    Returns:
        List containing service token.
    """
    client = api_client if api_client is not None else _get_api_client()
    try:
        response = await client.post(
            "/internal/service-tokens",
            json={"service_id": service_id, "service_secret": service_secret},
        )
        if response.status_code == 200:
            return [TextContent(type="text", text=json.dumps(response.json()))]
        else:
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "error": "GetServiceTokenFailed",
                            "details": f"Status {response.status_code}",
                        }
                    ),
                )
            ]
    except Exception as e:
        logger.exception("Error getting service token")
        return [
            TextContent(
                type="text",
                text=json.dumps({"error": "InternalError", "details": str(e)}),
            )
        ]


async def auth_validate_token(authorization: str) -> list[TextContent]:
    """Validate a bearer token and extract claims.

    Args:
        authorization: Bearer token from Authorization header.

    Returns:
        List containing token claims/user info.
    """
    client = api_client if api_client is not None else _get_api_client()
    try:
        headers = {"Authorization": authorization}
        response = await client.get("/api/v1/auth/me", headers=headers)
        if response.status_code == 200:
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "valid": True,
                            "claims": response.json(),
                        }
                    ),
                )
            ]
        elif response.status_code == 401:
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "valid": False,
                            "error": "Unauthorized",
                            "details": "Invalid or expired token",
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
                            "error": "ValidateTokenFailed",
                            "details": f"Status {response.status_code}",
                        }
                    ),
                )
            ]
    except Exception as e:
        logger.exception("Error validating token")
        return [
            TextContent(
                type="text",
                text=json.dumps({"error": "InternalError", "details": str(e)}),
            )
        ]
