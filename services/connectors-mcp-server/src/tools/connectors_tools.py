"""Connector tools for platform-connectors-mcp."""

import json
import logging
from typing import Any

from mcp.types import TextContent

from ..client.api_client import ConnectorsApiClient
from ..config.settings import Settings

logger = logging.getLogger(__name__)

# Lazy singleton pattern for test monkeypatching
_settings: Settings | None = None
_api_client: ConnectorsApiClient | None = None

# Module-level None sentinel for test monkeypatching
api_client: ConnectorsApiClient | None = None
settings: Settings | None = None


def _get_settings() -> Settings:
    """Get or create settings singleton."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def _get_api_client() -> ConnectorsApiClient:
    """Get or create API client singleton."""
    global _api_client
    if _api_client is None:
        _api_client = ConnectorsApiClient(_get_settings())
    return _api_client


async def connectors_health_check() -> list[TextContent]:
    """Check if platform-connectors service is healthy.

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


async def connectors_list() -> list[TextContent]:
    """List all available connectors (40+ adapters).

    Returns:
        List containing all connectors.
    """
    client = api_client if api_client is not None else _get_api_client()
    try:
        response = await client.get("/api/v1/connectors")
        if response.status_code == 200:
            return [TextContent(type="text", text=json.dumps(response.json()))]
        else:
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "error": "ListConnectorsFailed",
                            "details": f"Status {response.status_code}",
                        }
                    ),
                )
            ]
    except Exception as e:
        logger.exception("Error listing connectors")
        return [
            TextContent(
                type="text",
                text=json.dumps({"error": "InternalError", "details": str(e)}),
            )
        ]


async def connectors_get(connector_id: str) -> list[TextContent]:
    """Get a specific connector by ID.

    Args:
        connector_id: The connector identifier.

    Returns:
        List containing connector details.
    """
    client = api_client if api_client is not None else _get_api_client()
    try:
        response = await client.get(f"/api/v1/connectors/{connector_id}")
        if response.status_code == 200:
            return [TextContent(type="text", text=json.dumps(response.json()))]
        elif response.status_code == 404:
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "error": "NotFound",
                            "details": f"Connector '{connector_id}' not found",
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
                            "error": "GetConnectorFailed",
                            "details": f"Status {response.status_code}",
                        }
                    ),
                )
            ]
    except Exception as e:
        logger.exception("Error getting connector")
        return [
            TextContent(
                type="text",
                text=json.dumps({"error": "InternalError", "details": str(e)}),
            )
        ]


async def connectors_search(query: str) -> list[TextContent]:
    """Search connectors by name or query.

    Args:
        query: Search query string.

    Returns:
        List containing matching connectors.
    """
    client = api_client if api_client is not None else _get_api_client()
    try:
        response = await client.get("/api/v1/connectors/search", params={"q": query})
        if response.status_code == 200:
            return [TextContent(type="text", text=json.dumps(response.json()))]
        else:
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "error": "SearchConnectorsFailed",
                            "details": f"Status {response.status_code}",
                        }
                    ),
                )
            ]
    except Exception as e:
        logger.exception("Error searching connectors")
        return [
            TextContent(
                type="text",
                text=json.dumps({"error": "InternalError", "details": str(e)}),
            )
        ]


async def connectors_get_schema(connector_id: str) -> list[TextContent]:
    """Get configuration schema for a connector.

    Args:
        connector_id: The connector identifier.

    Returns:
        List containing the schema/config fields.
    """
    client = api_client if api_client is not None else _get_api_client()
    try:
        response = await client.get(f"/api/v1/connectors/{connector_id}/schema")
        if response.status_code == 200:
            return [TextContent(type="text", text=json.dumps(response.json()))]
        elif response.status_code == 404:
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "error": "NotFound",
                            "details": f"Connector '{connector_id}' not found",
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
                            "error": "GetSchemalFailed",
                            "details": f"Status {response.status_code}",
                        }
                    ),
                )
            ]
    except Exception as e:
        logger.exception("Error getting connector schema")
        return [
            TextContent(
                type="text",
                text=json.dumps({"error": "InternalError", "details": str(e)}),
            )
        ]


async def connectors_test_connection(connector_id: str, credentials: dict[str, Any]) -> list[TextContent]:
    """Test connection with provided credentials.

    Args:
        connector_id: The connector identifier.
        credentials: Configuration/credentials to test.

    Returns:
        List containing test result.
    """
    client = api_client if api_client is not None else _get_api_client()
    try:
        response = await client.post(
            f"/api/v1/connectors/{connector_id}/test",
            json=credentials,
        )
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
        elif response.status_code == 404:
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "error": "NotFound",
                            "details": f"Connector '{connector_id}' not found",
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
                            "error": "TestConnectionFailed",
                            "details": f"Status {response.status_code}",
                        }
                    ),
                )
            ]
    except Exception as e:
        logger.exception("Error testing connection")
        return [
            TextContent(
                type="text",
                text=json.dumps({"error": "InternalError", "details": str(e)}),
            )
        ]


async def connectors_list_credentials() -> list[TextContent]:
    """List user's stored connector credentials.

    Returns:
        List containing user's credentials.
    """
    client = api_client if api_client is not None else _get_api_client()
    try:
        response = await client.get("/api/v1/credentials")
        if response.status_code == 200:
            return [TextContent(type="text", text=json.dumps(response.json()))]
        else:
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "error": "ListCredentialsFailed",
                            "details": f"Status {response.status_code}",
                        }
                    ),
                )
            ]
    except Exception as e:
        logger.exception("Error listing credentials")
        return [
            TextContent(
                type="text",
                text=json.dumps({"error": "InternalError", "details": str(e)}),
            )
        ]


async def connectors_get_credential(credential_id: str) -> list[TextContent]:
    """Get a specific credential by ID.

    Args:
        credential_id: The credential identifier.

    Returns:
        List containing credential details.
    """
    client = api_client if api_client is not None else _get_api_client()
    try:
        response = await client.get(f"/api/v1/credentials/{credential_id}")
        if response.status_code == 200:
            return [TextContent(type="text", text=json.dumps(response.json()))]
        elif response.status_code == 404:
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "error": "NotFound",
                            "details": f"Credential '{credential_id}' not found",
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
                            "error": "GetCredentialFailed",
                            "details": f"Status {response.status_code}",
                        }
                    ),
                )
            ]
    except Exception as e:
        logger.exception("Error getting credential")
        return [
            TextContent(
                type="text",
                text=json.dumps({"error": "InternalError", "details": str(e)}),
            )
        ]
