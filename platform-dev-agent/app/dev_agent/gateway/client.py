"""Streamable HTTP client for the platform-mcp gateway.

Every tool is invoked as ``<namespace>.<operationId>`` via JSON-RPC
``tools/call`` over Streamable HTTP with OAuth 2.1. The client NEVER talks
REST directly to a backend and NEVER imports a tool in-process.

Idempotency contract (critique §1.9 / §4)
------------------------------------------
Every request carries an ``Idempotency-Key`` header. **The gateway does NOT
deduplicate writes by this key** — it only uses retries for *reads*. Therefore
resuming/retrying a *write* is NOT safe at this layer (it would duplicate the
side effect); that is the executor's responsibility (out of this skeleton) and
is gated by ``Settings.resume_writes_safe`` (default ``False``). To keep this
asymmetry explicit, retry (via tenacity) is applied ONLY to reads: the caller
passes ``capability`` to :meth:`call_tool` and writes are attempted exactly
once.

Correlation headers ``X-Run-Id`` / ``X-Session-Id`` / ``X-Agent-Profile`` /
``X-Initiated-By`` are attached to every call for traceability.
"""

from __future__ import annotations

from typing import Any, Protocol

import httpx

try:  # tenacity is a hard dep, but degrade gracefully if absent (marketing pattern)
    from tenacity import (
        AsyncRetrying,
        retry_if_exception_type,
        stop_after_attempt,
        wait_exponential,
    )

    _HAS_TENACITY = True
except ImportError:  # pragma: no cover - exercised only without tenacity installed
    _HAS_TENACITY = False

from app.dev_agent.models.plan import Capability


class TokenProvider(Protocol):
    """Async OAuth 2.1 token provider (client-credentials / refresh)."""

    async def get_token(self) -> str: ...


class GatewayError(RuntimeError):
    """A gateway HTTP or JSON-RPC error."""


class GatewayToolClient:
    """Streamable HTTP client for the platform-mcp gateway.

    Invokes tools registered on the gateway via ``tools/call``. Reads are
    retried with exponential backoff (parametrized); writes are attempted
    exactly once (see module docstring on idempotency).
    """

    def __init__(
        self,
        *,
        base_url: str,
        token_provider: TokenProvider,
        connect_timeout: float = 5.0,
        read_timeout: float = 120.0,
        write_timeout: float = 10.0,
        max_retries: int = 3,
        backoff_min: float = 1.0,
        backoff_max: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
        tenant_id: str | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._token_provider = token_provider
        # Default tenant. The REAL gateway REQUIRES X-Tenant-Id on EVERY request
        # (SEC-035), including tools/list — which has no per-call correlation. When
        # set, it is sent on all requests unless a per-call correlation overrides it.
        self._tenant_id = tenant_id
        self._timeout = httpx.Timeout(
            connect=connect_timeout,
            read=read_timeout,
            write=write_timeout,
            pool=read_timeout,
        )
        self._max_retries = max(1, int(max_retries))
        self._backoff_min = backoff_min
        self._backoff_max = backoff_max
        # Optional injected transport (e.g. httpx.ASGITransport(app=fake_gateway))
        # for tests — lets a fake gateway be exercised over the *real* httpx stack
        # (JSON-RPC, headers, retry) without opening a socket. None => production
        # behaviour (httpx's default transport). Semantics are otherwise unchanged.
        self._transport = transport

    async def list_tools(self) -> Any:
        """List tools registered on the gateway (a read; retried)."""
        return await self._retrying_read(lambda: self._rpc("tools/list", {}, "tools/list"))

    async def call_tool(
        self,
        tool: str,
        arguments: dict[str, Any],
        *,
        idempotency_key: str,
        capability: Capability = Capability.READ,
        correlation: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Invoke ``tool`` (``<namespace>.<operationId>``) via ``tools/call``.

        Always sends the ``Idempotency-Key`` header. Retries transient network
        errors ONLY when ``capability`` is READ; writes are attempted once.
        """

        async def _once() -> dict[str, Any]:
            payload = {
                "jsonrpc": "2.0",
                # JSON-RPC correlation id is intentionally distinct from the
                # dedup key; use the idempotency key value only as a convenient
                # request id (critique §1.9 warns against conflating them, so we
                # keep the *semantics* separate even where the value coincides).
                "id": idempotency_key,
                "method": "tools/call",
                "params": {"name": tool, "arguments": arguments},
            }
            headers = await self._headers(correlation, idempotency_key)
            async with httpx.AsyncClient(
                timeout=self._timeout, transport=self._transport
            ) as client:
                resp = await client.post(self._base_url, json=payload, headers=headers)
                if resp.status_code >= 400:
                    raise GatewayError(
                        f"gateway HTTP {resp.status_code} on {tool}: {resp.text[:400]}"
                    )
                body = resp.json()
                if "error" in body:
                    raise GatewayError(f"gateway RPC error on {tool}: {body['error']}")
                return body.get("result", {})

        if capability is Capability.READ:
            return await self._retrying_read(_once)
        # WRITE: attempt exactly once (no retry — gateway does not dedup writes).
        return await _once()

    async def _rpc(self, method: str, params: dict, request_id: str) -> Any:
        headers = await self._headers(None, request_id)
        payload = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        async with httpx.AsyncClient(
            timeout=self._timeout, transport=self._transport
        ) as client:
            resp = await client.post(self._base_url, json=payload, headers=headers)
            if resp.status_code >= 400:
                raise GatewayError(f"gateway HTTP {resp.status_code} on {method}: {resp.text[:400]}")
            body = resp.json()
            if "error" in body:
                raise GatewayError(f"gateway RPC error on {method}: {body['error']}")
            return body.get("result", {})

    async def _retrying_read(self, fn):
        """Run ``fn`` with tenacity retry on transient network errors (reads only)."""
        if not _HAS_TENACITY or self._max_retries <= 1:
            return await fn()
        async for attempt in AsyncRetrying(
            retry=retry_if_exception_type((httpx.TransportError, httpx.TimeoutException)),
            stop=stop_after_attempt(self._max_retries),
            wait=wait_exponential(multiplier=1, min=self._backoff_min, max=self._backoff_max),
            reraise=True,
        ):
            with attempt:
                return await fn()
        raise AssertionError("unreachable: AsyncRetrying always returns or raises")

    async def _headers(
        self, correlation: dict[str, str] | None, idempotency_key: str
    ) -> dict[str, str]:
        token = await self._token_provider.get_token()  # OAuth 2.1
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",  # Streamable HTTP
            "Idempotency-Key": idempotency_key,  # ALWAYS sent
        }
        # Default tenant applies to every request (incl. tools/list, which has no
        # correlation); a per-call correlation "Tenant-Id" still wins.
        if self._tenant_id:
            headers["X-Tenant-Id"] = self._tenant_id
        for key, value in (correlation or {}).items():
            headers[f"X-{key}"] = value
        return headers


def build_correlation(
    *,
    run_id: str,
    session_id: str,
    agent_profile: str,
    initiated_by: str = "agent",
    tenant_id: str | None = None,
) -> dict[str, str]:
    """Build the correlation dict consumed by :meth:`GatewayToolClient.call_tool`.

    Produces headers ``X-Run-Id`` / ``X-Session-Id`` / ``X-Agent-Profile`` /
    ``X-Initiated-By`` and, when ``tenant_id`` is given, ``X-Tenant-Id`` — which
    the REAL platform-mcp gateway REQUIRES (SEC-035). The in-process fake gateway
    does not need it, so it stays optional (``None`` for the local E2E).
    """
    correlation = {
        "Run-Id": run_id,
        "Session-Id": session_id,
        "Agent-Profile": agent_profile,
        "Initiated-By": initiated_by,
    }
    if tenant_id:
        correlation["Tenant-Id"] = tenant_id
    return correlation
