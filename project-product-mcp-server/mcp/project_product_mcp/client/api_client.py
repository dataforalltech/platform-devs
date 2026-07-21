"""HTTP client for the service-private MCP adapter.

All calls target /api/internal/mcp/*. The client uses only the Vault-bootstrap
S2S credential configured for this sidecar-to-adapter relationship. Tenant,
correlation and execution depth arrive as TrustedMcpContext after the HTTP
sidecar re-verifies the inner token; tool arguments never create this context.
"""

from __future__ import annotations

import json as jsonlib
import logging
from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote, urlsplit

import httpx

from ..config.settings import Settings, validate_service_base_url

_log = logging.getLogger(__name__)

_ADAPTER_PREFIX = "/api/internal/mcp/"


@dataclass(frozen=True)
class TrustedMcpContext:
    """Context derived from a verified inner token and tenant-global domain semantics."""

    tenant_id: str
    actor_id: int
    environment_id: int
    correlation_id: str | None
    execution_depth: int


class AdapterUnavailableError(RuntimeError):
    """Transport or timeout failure while reaching the private adapter."""


class AdapterResponseError(RuntimeError):
    """An adapter HTTP or response-contract failure, without its response body."""

    def __init__(self, status_code: int) -> None:
        super().__init__(f"adapter returned HTTP {status_code}")
        self.status_code = status_code


class ServiceApiClient:
    """Narrow S2S client for service-specific private MCP adapters."""

    def __init__(self, settings: Settings) -> None:
        base_url = validate_service_base_url(
            settings.SERVICE_BASE_URL,
            allowed_hosts=settings.SERVICE_ALLOWED_HOSTS,
            runtime_env=settings.RUNTIME_ENV,
            private_network_encrypted=settings.PRIVATE_NETWORK_ENCRYPTED,
            tls_verify=settings.SERVICE_TLS_VERIFY,
            tls_client_cert_file=settings.SERVICE_TLS_CLIENT_CERT_FILE,
            tls_client_key_file=settings.SERVICE_TLS_CLIENT_KEY_FILE,
        )
        token = settings.INTERNAL_API_TOKEN
        if token is None or not token.get_secret_value():
            raise RuntimeError("INTERNAL_API_TOKEN was not resolved during sidecar bootstrap")

        verify: bool | str = settings.SERVICE_TLS_CA_FILE or settings.SERVICE_TLS_VERIFY
        cert: tuple[str, str] | None = None
        if settings.SERVICE_TLS_CLIENT_CERT_FILE and settings.SERVICE_TLS_CLIENT_KEY_FILE:
            cert = (
                settings.SERVICE_TLS_CLIENT_CERT_FILE,
                settings.SERVICE_TLS_CLIENT_KEY_FILE,
            )

        self._max_response_body_bytes = settings.MCP_MAX_RESPONSE_BODY_BYTES
        self._service_identity = settings.APP_NAME
        self._readiness_url = settings.SERVICE_READINESS_URL
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={
                "X-Internal-Token": token.get_secret_value(),
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=settings.MCP_REQUEST_TIMEOUT_SECONDS,
            follow_redirects=False,
            trust_env=False,
            verify=verify,
            cert=cert,
        )
        self._readiness_client = httpx.AsyncClient(
            headers={"Accept": "application/json"},
            timeout=settings.MCP_REQUEST_TIMEOUT_SECONDS,
            follow_redirects=False,
            trust_env=False,
            verify=verify,
            cert=cert,
        )

    @staticmethod
    def _adapter_path(path: str) -> str:
        """Allow only a canonical relative path below the private adapter prefix."""
        parsed = urlsplit(path)
        decoded_path = unquote(parsed.path)
        if (
            parsed.scheme
            or parsed.netloc
            or parsed.query
            or parsed.fragment
            or parsed.path != path
            or not decoded_path.startswith(_ADAPTER_PREFIX)
            or "\\" in decoded_path
            or "%" in path
            or any(segment in {".", ".."} for segment in decoded_path.split("/"))
        ):
            raise ValueError("MCP sidecar may call only /api/internal/mcp/* adapters")
        return path

    @staticmethod
    def _trusted_context_headers(context: TrustedMcpContext) -> dict[str, str]:
        """Build headers only from sidecar-validated execution context."""
        if not context.tenant_id:
            raise ValueError("tenant context must come from a re-verified inner token")
        if context.execution_depth < 1:
            raise ValueError("execution depth must be incremented before adapter dispatch")

        headers = {
            "X-Tenant-Id": context.tenant_id,
            "X-Actor-Id": str(context.actor_id),
            "X-Execution-Depth": str(context.execution_depth),
        }
        if context.correlation_id:
            headers["X-Correlation-Id"] = context.correlation_id
        headers["X-Service-Identity"] = "platform-project-product-mcp"
        return headers

    async def _read_limited_body(self, response: httpx.Response) -> bytes:
        """Read a decoded response stream without ever buffering past the limit."""
        declared_length = response.headers.get("Content-Length")
        if declared_length is not None:
            try:
                parsed_length = int(declared_length)
            except ValueError as exc:
                raise AdapterResponseError(502) from exc
            if parsed_length < 0 or parsed_length > self._max_response_body_bytes:
                _log.warning("service_adapter_response_too_large source=content_length")
                raise AdapterResponseError(502)

        body = bytearray()
        # A bounded decoded chunk size also constrains individual chunks produced
        # when a compressed upstream response expands substantially.
        chunk_size = min(65_536, self._max_response_body_bytes + 1)
        async for chunk in response.aiter_bytes(chunk_size=chunk_size):
            if len(body) + len(chunk) > self._max_response_body_bytes:
                _log.warning("service_adapter_response_too_large source=stream")
                raise AdapterResponseError(502)
            body.extend(chunk)
        return bytes(body)

    async def _handle(self, response: httpx.Response) -> dict[str, Any]:
        if response.status_code == 204:
            return {"ok": True, "status": response.status_code}
        body = await self._read_limited_body(response)
        if not body:
            return {"ok": True, "status": response.status_code}
        try:
            payload = jsonlib.loads(body)
        except (ValueError, RecursionError) as exc:
            _log.warning("service_adapter_invalid_response status=%s", response.status_code)
            raise AdapterResponseError(502) from exc
        return payload if isinstance(payload, dict) else {"data": payload}

    async def _request(
        self,
        method: str,
        path: str,
        *,
        context: TrustedMcpContext,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Call the adapter without collapsing transport/HTTP failures into data."""
        adapter_path = self._adapter_path(path)
        headers = self._trusted_context_headers(context)
        try:
            async with self._client.stream(
                method,
                adapter_path,
                params=params,
                json=json,
                headers=headers,
            ) as response:
                if not response.is_success:
                    _log.warning(
                        "service_adapter_error method=%s status=%s",
                        method,
                        response.status_code,
                    )
                    raise AdapterResponseError(response.status_code)
                return await self._handle(response)
        except httpx.RequestError as exc:
            _log.warning(
                "service_adapter_unavailable method=%s type=%s", method, type(exc).__name__
            )
            raise AdapterUnavailableError("private adapter is unreachable") from exc

    async def get(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        context: TrustedMcpContext,
    ) -> dict[str, Any]:
        return await self._request("GET", path, params=params, context=context)

    async def post(
        self,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        context: TrustedMcpContext,
    ) -> dict[str, Any]:
        return await self._request("POST", path, json=json, params=params, context=context)

    async def patch(
        self,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        context: TrustedMcpContext,
    ) -> dict[str, Any]:
        return await self._request("PATCH", path, json=json, context=context)

    async def delete(
        self,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        context: TrustedMcpContext,
    ) -> dict[str, Any]:
        return await self._request("DELETE", path, json=json, context=context)

    async def readiness(self) -> None:
        """Require the private API's real management readiness endpoint."""
        try:
            response = await self._readiness_client.get(self._readiness_url)
        except httpx.RequestError as exc:
            raise AdapterUnavailableError("private adapter readiness is unreachable") from exc
        if not response.is_success:
            raise AdapterResponseError(response.status_code)

    async def aclose(self) -> None:
        """Release the private HTTP connection pool during controlled shutdown."""
        await self._client.aclose()
        await self._readiness_client.aclose()
