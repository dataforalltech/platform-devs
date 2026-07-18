"""Exchange the caller token for a provider-audience inner token."""

from __future__ import annotations

import os

import httpx


class TokenExchangeUnavailable(RuntimeError):
    pass


async def exchange_token(authorization: str, provider: str) -> str:
    url = os.environ.get("GATEWAY_TOKEN_EXCHANGE_URL")
    if not url:
        raise TokenExchangeUnavailable("GATEWAY_TOKEN_EXCHANGE_URL is required")
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(
                url,
                headers={"Authorization": authorization},
                json={"audience": f"mcp:{provider}"},
            )
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise TokenExchangeUnavailable("inner-token exchange unavailable") from exc
    token = payload.get("access_token")
    if not isinstance(token, str) or not token:
        raise TokenExchangeUnavailable("token exchange returned no access_token")
    return token
