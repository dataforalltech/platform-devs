"""Cache tools for platform-cache-mcp."""

import json
import logging
from typing import Any

from mcp.types import TextContent

from ..client.api_client import CacheApiClient
from ..config.settings import Settings

logger = logging.getLogger(__name__)

# Lazy singleton pattern for test monkeypatching
_settings: Settings | None = None
_api_client: CacheApiClient | None = None

# Module-level None sentinel for test monkeypatching
api_client: CacheApiClient | None = None
settings: Settings | None = None


def _get_settings() -> Settings:
    """Get or create settings singleton."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def _get_api_client() -> CacheApiClient:
    """Get or create API client singleton."""
    global _api_client
    if _api_client is None:
        _api_client = CacheApiClient(_get_settings())
    return _api_client


async def cache_health_check() -> list[TextContent]:
    """Check if platform-cache service is healthy.

    Returns:
        List containing health status response.
    """
    client = api_client if api_client is not None else _get_api_client()
    try:
        response = await client.get("/health")
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


async def cache_set(
    key: str,
    value: str,
    ttl: int | None = None,
) -> list[TextContent]:
    """Set a cache key-value pair with optional TTL.

    Args:
        key: The cache key.
        value: The value to cache.
        ttl: Time-to-live in seconds (optional).

    Returns:
        List containing operation result.
    """
    client = api_client if api_client is not None else _get_api_client()
    try:
        payload: dict[str, Any] = {"key": key, "value": value}
        if ttl is not None:
            payload["ttl"] = ttl

        response = await client.post("/cache/set", json=payload)
        if response.status_code == 200:
            return [TextContent(type="text", text=json.dumps(response.json()))]
        elif response.status_code == 400:
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "error": "InvalidRequest",
                            "details": "Invalid key or value format",
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
                            "error": "SetFailed",
                            "details": f"Status {response.status_code}",
                        }
                    ),
                )
            ]
    except Exception as e:
        logger.exception("Error setting cache")
        return [
            TextContent(
                type="text",
                text=json.dumps({"error": "InternalError", "details": str(e)}),
            )
        ]


async def cache_get(key: str) -> list[TextContent]:
    """Get a value from cache by key.

    Args:
        key: The cache key.

    Returns:
        List containing cached value or error.
    """
    client = api_client if api_client is not None else _get_api_client()
    try:
        response = await client.get(f"/cache/get/{key}")
        if response.status_code == 200:
            return [TextContent(type="text", text=json.dumps(response.json()))]
        elif response.status_code == 404:
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "error": "KeyNotFound",
                            "details": f"Key {key} not found in cache",
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
                            "error": "GetFailed",
                            "details": f"Status {response.status_code}",
                        }
                    ),
                )
            ]
    except Exception as e:
        logger.exception("Error getting cache")
        return [
            TextContent(
                type="text",
                text=json.dumps({"error": "InternalError", "details": str(e)}),
            )
        ]


async def cache_delete(key: str) -> list[TextContent]:
    """Delete a key from cache.

    Args:
        key: The cache key to delete.

    Returns:
        List containing deletion result.
    """
    client = api_client if api_client is not None else _get_api_client()
    try:
        response = await client.delete(f"/cache/delete/{key}")
        if response.status_code == 200:
            return [TextContent(type="text", text=json.dumps(response.json()))]
        elif response.status_code == 404:
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "error": "KeyNotFound",
                            "details": f"Key {key} not found in cache",
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
                            "error": "DeleteFailed",
                            "details": f"Status {response.status_code}",
                        }
                    ),
                )
            ]
    except Exception as e:
        logger.exception("Error deleting cache")
        return [
            TextContent(
                type="text",
                text=json.dumps({"error": "InternalError", "details": str(e)}),
            )
        ]


async def cache_clear_all() -> list[TextContent]:
    """Clear all cache entries.

    Returns:
        List containing operation result.
    """
    client = api_client if api_client is not None else _get_api_client()
    try:
        response = await client.delete("/cache/clear")
        if response.status_code == 200:
            return [TextContent(type="text", text=json.dumps(response.json()))]
        else:
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "error": "ClearFailed",
                            "details": f"Status {response.status_code}",
                        }
                    ),
                )
            ]
    except Exception as e:
        logger.exception("Error clearing cache")
        return [
            TextContent(
                type="text",
                text=json.dumps({"error": "InternalError", "details": str(e)}),
            )
        ]


async def cache_get_stats() -> list[TextContent]:
    """Get cache hit/miss statistics.

    Returns:
        List containing cache statistics.
    """
    client = api_client if api_client is not None else _get_api_client()
    try:
        response = await client.get("/cache/stats")
        if response.status_code == 200:
            return [TextContent(type="text", text=json.dumps(response.json()))]
        else:
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "error": "StatsFailed",
                            "details": f"Status {response.status_code}",
                        }
                    ),
                )
            ]
    except Exception as e:
        logger.exception("Error getting cache stats")
        return [
            TextContent(
                type="text",
                text=json.dumps({"error": "InternalError", "details": str(e)}),
            )
        ]


async def cache_set_pattern(
    pattern: str,
    values: dict[str, str],
    ttl: int | None = None,
) -> list[TextContent]:
    """Set multiple cache keys with a pattern prefix.

    Args:
        pattern: Pattern prefix for all keys (e.g., "user:123:*").
        values: Dictionary of key suffixes to values.
        ttl: Time-to-live in seconds (optional, applied to all keys).

    Returns:
        List containing operation result.
    """
    client = api_client if api_client is not None else _get_api_client()
    try:
        payload: dict[str, Any] = {
            "pattern": pattern,
            "values": values,
        }
        if ttl is not None:
            payload["ttl"] = ttl

        response = await client.post("/cache/set-pattern", json=payload)
        if response.status_code == 200:
            return [TextContent(type="text", text=json.dumps(response.json()))]
        elif response.status_code == 400:
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "error": "InvalidRequest",
                            "details": "Invalid pattern or values format",
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
                            "error": "SetPatternFailed",
                            "details": f"Status {response.status_code}",
                        }
                    ),
                )
            ]
    except Exception as e:
        logger.exception("Error setting cache pattern")
        return [
            TextContent(
                type="text",
                text=json.dumps({"error": "InternalError", "details": str(e)}),
            )
        ]


async def cache_increment(
    key: str,
    amount: int = 1,
) -> list[TextContent]:
    """Atomically increment a numeric cache value.

    Args:
        key: The cache key.
        amount: Amount to increment (default 1).

    Returns:
        List containing new value or error.
    """
    client = api_client if api_client is not None else _get_api_client()
    try:
        payload = {
            "key": key,
            "amount": amount,
        }
        response = await client.put("/cache/increment", json=payload)
        if response.status_code == 200:
            return [TextContent(type="text", text=json.dumps(response.json()))]
        elif response.status_code == 400:
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "error": "InvalidRequest",
                            "details": "Invalid key or amount format",
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
                            "error": "KeyNotFound",
                            "details": f"Key {key} not found in cache",
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
                            "error": "IncrementFailed",
                            "details": f"Status {response.status_code}",
                        }
                    ),
                )
            ]
    except Exception as e:
        logger.exception("Error incrementing cache")
        return [
            TextContent(
                type="text",
                text=json.dumps({"error": "InternalError", "details": str(e)}),
            )
        ]
