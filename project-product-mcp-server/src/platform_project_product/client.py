"""Async typed client for the public service contract."""

from __future__ import annotations

from typing import Any

import httpx


class ProjectProductClient:
    def __init__(self, base_url: str, token: str, *, timeout_seconds: float = 10.0) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout_seconds,
            follow_redirects=False,
            trust_env=False,
        )

    async def request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        response = await self._client.request(
            method,
            path,
            json=json,
            params=params,
        )
        response.raise_for_status()
        if response.status_code == 204 or not response.content:
            return None
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Project/product API response must be a JSON object")
        return payload

    async def aclose(self) -> None:
        await self._client.aclose()
