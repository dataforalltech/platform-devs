from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from project_product_mcp.client.api_client import (
    AdapterResponseError,
    AdapterUnavailableError,
    ServiceApiClient,
    TrustedMcpContext,
)
from project_product_mcp.config import settings as config
from pydantic import SecretStr

from platform_project_product.client import ProjectProductClient

TENANT = "11111111-1111-4111-8111-111111111111"
CONTEXT = TrustedMcpContext(TENANT, 7, 0, "request-1", 1)


class Vault:
    def __init__(self, value=None, error: Exception | None = None):
        self.value = value
        self.error = error

    def get(self, _name, *, field):
        assert field == "value"
        if self.error:
            raise self.error
        return self.value


def bare_client(handler, *, max_bytes=1024) -> ServiceApiClient:
    client = object.__new__(ServiceApiClient)
    client._max_response_body_bytes = max_bytes
    client._service_identity = "platform-project-product-mcp"
    client._client = httpx.AsyncClient(
        base_url="http://service.invalid",
        transport=httpx.MockTransport(handler),
    )
    client._readiness_url = "http://service.invalid/health/ready"
    client._readiness_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return client


def test_secret_resolution_local_cloud_and_sanitized_failures(monkeypatch):
    monkeypatch.delenv("VAULT_ADDR", raising=False)
    assert config._secret_text(SecretStr("secret")) == "secret"
    assert config._secret_text("") is None
    assert (
        config.load_secret(
            "x",
            service="svc",
            runtime_env="local",
            local_value="fallback",
        )
        == "fallback"
    )
    assert (
        config.load_secret(
            "x",
            service="svc",
            runtime_env="cloud",
            local_value="ignored",
            client=Vault("vault"),
        )
        == "vault"
    )
    assert (
        config.load_secret(
            "x",
            service="svc",
            runtime_env="local",
            local_value="fallback",
            client=Vault(error=OSError("sensitive")),
        )
        == "fallback"
    )
    assert (
        config.load_secret(
            "x",
            service="svc",
            runtime_env="local",
            local_value=None,
            client=Vault(None),
            required=False,
        )
        is None
    )
    with pytest.raises(config.SecretResolutionError, match="cloud secret"):
        config.load_secret(
            "x",
            service="svc",
            runtime_env="cloud",
            local_value="ignored",
            client=Vault(error=OSError("sensitive")),
        )
    with pytest.raises(config.SecretResolutionError, match="missing"):
        config.load_secret(
            "x",
            service="svc",
            runtime_env="local",
            local_value=None,
        )
    with pytest.raises(ValueError, match="RUNTIME_ENV"):
        config.load_secret(
            "x",
            service="svc",
            runtime_env="invalid",
            local_value=None,
        )


@pytest.mark.parametrize(
    "value",
    ["", "bad/path", "user@host", "white space", "169.254.169.254"],
)
def test_destination_host_rejects_unsafe_values(value):
    with pytest.raises(ValueError):
        config._validate_destination_host(value, runtime_env="cloud")


def test_url_validation_allowlists_tls_and_network_rules():
    assert (
        config.validate_service_base_url(
            "http://service.invalid:8000/",
            allowed_hosts=["SERVICE.INVALID"],
            runtime_env="local",
            private_network_encrypted=False,
            tls_verify=True,
            tls_client_cert_file=None,
            tls_client_key_file=None,
        )
        == "http://service.invalid:8000"
    )
    base = dict(
        allowed_hosts=["service.invalid"],
        runtime_env="cloud",
        private_network_encrypted=True,
        tls_verify=True,
        tls_client_cert_file=None,
        tls_client_key_file=None,
    )
    invalid = [
        ("http://other.invalid", {}),
        ("https://service.invalid/path", {}),
        ("https://user:password@service.invalid", {}),
        ("https://service.invalid?query=1", {}),
        ("https://service.invalid", {"tls_verify": False}),
        ("http://service.invalid", {"tls_client_cert_file": "cert"}),
        ("https://service.invalid", {"tls_client_cert_file": "cert"}),
    ]
    for value, changes in invalid:
        kwargs = dict(base)
        kwargs.update(changes)
        with pytest.raises(ValueError):
            config.validate_service_base_url(value, **kwargs)
    with pytest.raises(ValueError, match="cloud HTTP"):
        config.validate_service_base_url(
            "http://service.invalid",
            **{**base, "private_network_encrypted": False},
        )
    assert config.validate_dependency_endpoint_url(
        "https://service.invalid:9090/health/ready",
        allowed_hosts=["service.invalid"],
        runtime_env="cloud",
        private_network_encrypted=False,
        tls_verify=True,
    ).endswith("/health/ready")
    with pytest.raises(ValueError, match="allowlist"):
        config.validate_dependency_endpoint_url(
            "https://other.invalid/health/ready",
            allowed_hosts=["service.invalid"],
            runtime_env="cloud",
            private_network_encrypted=False,
            tls_verify=True,
        )


def test_adapter_path_and_context_are_strict():
    assert ServiceApiClient._adapter_path("/api/internal/mcp/products") == (
        "/api/internal/mcp/products"
    )
    for path in [
        "https://evil.invalid/api/internal/mcp/products",
        "/api/internal/mcp/../admin",
        "/api/internal/mcp/%2e%2e/admin",
        "/api/v1/products",
        "/api/internal/mcp/products?x=1",
        "/api/internal/mcp\\products",
    ]:
        with pytest.raises(ValueError):
            ServiceApiClient._adapter_path(path)
    headers = ServiceApiClient._trusted_context_headers(CONTEXT)
    assert headers["X-Tenant-Id"] == TENANT
    assert headers["X-Correlation-Id"] == "request-1"
    assert "X-Environment-Id" not in headers
    with pytest.raises(ValueError):
        ServiceApiClient._trusted_context_headers(TrustedMcpContext("", 7, 2, None, 1))
    with pytest.raises(ValueError):
        ServiceApiClient._trusted_context_headers(TrustedMcpContext(TENANT, 7, 2, None, 0))


@pytest.mark.asyncio
async def test_adapter_client_success_headers_and_methods():
    captured = []

    def handler(request: httpx.Request):
        captured.append(request)
        if request.url.path.endswith("/empty"):
            return httpx.Response(204)
        if request.url.path.endswith("/list"):
            return httpx.Response(200, json=[1, 2])
        return httpx.Response(200, json={"ok": True})

    client = bare_client(handler)
    assert await client.get(
        "/api/internal/mcp/products",
        params={"limit": 2},
        context=CONTEXT,
    ) == {"ok": True}
    assert await client.post(
        "/api/internal/mcp/products",
        json={"name": "p"},
        context=CONTEXT,
    ) == {"ok": True}
    assert await client.patch(
        "/api/internal/mcp/products/1",
        json={"name": "p"},
        context=CONTEXT,
    ) == {"ok": True}
    assert await client.delete(
        "/api/internal/mcp/empty",
        context=CONTEXT,
    ) == {"ok": True, "status": 204}
    assert await client.get(
        "/api/internal/mcp/list",
        context=CONTEXT,
    ) == {"data": [1, 2]}
    await client.readiness()
    assert all(
        item.headers["X-Service-Identity"] == "platform-project-product-mcp"
        for item in captured
        if item.url.path.startswith("/api/internal/mcp/")
    )
    await client.aclose()


@pytest.mark.asyncio
async def test_adapter_client_failures_are_typed_and_bounded():
    def handler(request: httpx.Request):
        if request.url.path.endswith("/status"):
            return httpx.Response(409, json={"secret": "not propagated"})
        if request.url.path.endswith("/invalid"):
            return httpx.Response(200, content=b"not-json")
        if request.url.path.endswith("/length"):
            return httpx.Response(200, headers={"Content-Length": "bad"}, content=b"{}")
        if request.url.path.endswith("/large"):
            return httpx.Response(200, content=b"x" * 20)
        raise httpx.ConnectError("down", request=request)

    client = bare_client(handler, max_bytes=8)
    with pytest.raises(AdapterResponseError) as status:
        await client.get("/api/internal/mcp/status", context=CONTEXT)
    assert status.value.status_code == 409
    for path in ("invalid", "length", "large"):
        with pytest.raises(AdapterResponseError) as exc:
            await client.get(f"/api/internal/mcp/{path}", context=CONTEXT)
        assert exc.value.status_code == 502
    with pytest.raises(AdapterUnavailableError):
        await client.get("/api/internal/mcp/down", context=CONTEXT)
    await client.aclose()


@pytest.mark.asyncio
async def test_public_typed_client_propagates_status_and_context():
    captured = []

    def handler(request: httpx.Request):
        captured.append(request)
        if request.url.path == "/empty":
            return httpx.Response(204)
        if request.url.path == "/fail":
            return httpx.Response(403, json={"error": "denied"})
        if request.url.path == "/list":
            return httpx.Response(200, json=[{"id": 1}])
        return httpx.Response(200, json={"ok": True})

    client = ProjectProductClient("http://service.invalid/", "token")
    await client._client.aclose()
    client._client = httpx.AsyncClient(
        base_url="http://service.invalid",
        transport=httpx.MockTransport(handler),
        headers={"Authorization": "Bearer token"},
    )
    assert await client.request("GET", "/ok") == {"ok": True}
    assert await client.request("DELETE", "/empty") is None
    with pytest.raises(httpx.HTTPStatusError):
        await client.request("GET", "/fail")
    with pytest.raises(ValueError, match="JSON object"):
        await client.request("GET", "/list")
    assert "X-Environment-Id" not in captured[0].headers
    await client.aclose()


@pytest.mark.asyncio
async def test_adapter_constructor_uses_validated_settings():
    settings = config.get_settings()
    client = ServiceApiClient(settings)
    assert client._service_identity == settings.APP_NAME
    await client.aclose()

    broken = SimpleNamespace(**settings.model_dump())
    broken.INTERNAL_API_TOKEN = None
    with pytest.raises(RuntimeError, match="INTERNAL_API_TOKEN"):
        ServiceApiClient(broken)
