"""HTTP client for platform-governance API."""

from typing import Any

import httpx

from ..config.settings import Settings


class GovernanceApiClient:
    """Async HTTP client for platform-governance API."""

    def __init__(self, settings: Settings) -> None:
        """Initialize the API client.

        Args:
            settings: Configuration settings with base_url and internal_token.
        """
        headers = {}
        if settings.internal_token:
            headers["X-Internal-Token"] = settings.internal_token

        self._client = httpx.AsyncClient(
            base_url=settings.base_url,
            headers=headers,
            timeout=settings.request_timeout,
        )

    async def get(self, path: str, **kwargs: Any) -> httpx.Response:
        """Perform a GET request."""
        return await self._client.get(path, **kwargs)

    async def post(
        self,
        path: str,
        json: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        """Perform a POST request."""
        return await self._client.post(path, json=json, **kwargs)

    async def put(
        self,
        path: str,
        json: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        """Perform a PUT request."""
        return await self._client.put(path, json=json, **kwargs)

    async def delete(self, path: str, **kwargs: Any) -> httpx.Response:
        """Perform a DELETE request."""
        return await self._client.delete(path, **kwargs)

    async def close(self) -> None:
        """Close the HTTP client."""
        await self._client.aclose()
