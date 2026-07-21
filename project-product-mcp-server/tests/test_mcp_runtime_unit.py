from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from project_product_mcp.client.api_client import (
    AdapterResponseError,
    AdapterUnavailableError,
    TrustedMcpContext,
)

from project_product_mcp import schemas as mcp_schemas
from project_product_mcp.server import mcp_server as server

TENANT = "devteam"
RESOURCE_ID = "11111111-1111-4111-8111-111111111111"


class MutableRateStore:
    shared = True

    def __init__(self) -> None:
        self.allowed = True
        self.error = False
        self.started = 0
        self.closed = 0

    async def startup(self) -> None:
        self.started += 1

    async def readiness(self) -> None:
        if self.error:
            raise RuntimeError("redis unavailable")

    async def close(self) -> None:
        self.closed += 1

    async def allow(self, *_args, **_kwargs):
        if self.error:
            raise RuntimeError("redis unavailable")
        return server.RateLimitDecision(self.allowed, 7)


class MutablePolicy:
    def __init__(self) -> None:
        self.decision = server.PolicyDecision("allow")
        self.error = False
        self.closed = 0

    async def evaluate(self, **_kwargs):
        if self.error:
            raise RuntimeError("governance unavailable")
        return self.decision

    async def readiness(self) -> None:
        if self.error:
            raise RuntimeError("governance unavailable")

    async def aclose(self) -> None:
        self.closed += 1


def claims() -> dict:
    return {
        "exp": 160,
        "iat": 100,
        "iss": "platform-admin/twin",
        "aud": "mcp:portfolio",
        "jti": "inner-1",
        "parent_jti": "front-1",
        "sub": "user:7",
        "tenant_id": TENANT,
        "scopes": ["portfolio:product:read"],
        "twin_id": "twin-1",
    }


async def verified(*_args, **_kwargs):
    return claims()


def body(token: str | None = "token") -> dict:
    metadata = {} if token is None else {"twin_token": token}
    return {
        "params": {
            "name": "product_get",
            "arguments": {"product_id": RESOURCE_ID},
            "_meta": metadata,
        }
    }


def product_result() -> dict:
    return {
        "product_id": RESOURCE_ID,
        "slug": "product",
        "name": "Product",
        "description": None,
        "status": "active",
        "owner_user_refs": [],
        "version": 1,
        "created_at": "2026-07-19T00:00:00Z",
        "updated_at": "2026-07-19T00:00:00Z",
        "created_by_ref": "platform-admin:user:7",
        "updated_by_ref": "platform-admin:user:7",
    }


def request(headers: dict[str, str] | None = None) -> Request:
    encoded = [
        (name.lower().encode("ascii"), value.encode("ascii"))
        for name, value in (headers or {}).items()
    ]
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/mcp/tools/call",
            "headers": encoded,
            "state": {"request_id": "request-1"},
            "client": ("127.0.0.1", 1234),
        }
    )


@pytest.mark.asyncio
async def test_rate_limit_backends_and_helpers(monkeypatch):
    clock = SimpleNamespace(value=120)
    monkeypatch.setattr(server.time, "time", lambda: clock.value)
    store = server.InMemoryRateLimitStore()
    await store.startup()
    assert (await store.allow("a", limit=1, window_seconds=60)).allowed is True
    assert (await store.allow("a", limit=1, window_seconds=60)).allowed is False
    clock.value = 240
    assert (await store.allow("a", limit=1, window_seconds=60)).allowed is True
    await store.close()
    assert store._counts == {}

    with pytest.raises(RuntimeError, match="required"):
        server.RedisRateLimitStore(SimpleNamespace(RATE_LIMIT_STORAGE_URI=None))

    fake = SimpleNamespace(
        ping=AsyncMock(),
        eval=AsyncMock(return_value=[2, -1]),
        aclose=AsyncMock(),
    )
    redis_store = object.__new__(server.RedisRateLimitStore)
    redis_store._prefix = "mcp"
    redis_store._client = fake
    await redis_store.startup()
    decision = await redis_store.allow("digest", limit=1, window_seconds=60)
    assert decision == server.RateLimitDecision(False, 1)
    await redis_store.close()
    fake.ping.side_effect = OSError("down")
    with pytest.raises(RuntimeError, match="unavailable"):
        await redis_store.startup()

    local = server._build_rate_limit_store(
        SimpleNamespace(RATE_LIMIT_STORAGE_URI=None, RUNTIME_ENV="local")
    )
    assert isinstance(local, server.InMemoryRateLimitStore)
    with pytest.raises(RuntimeError, match="shared"):
        server._build_rate_limit_store(
            SimpleNamespace(RATE_LIMIT_STORAGE_URI=None, RUNTIME_ENV="cloud")
        )

    valid_scope = {"headers": [(b"x-request-id", b"request-1")]}
    assert server._request_id_from_scope(valid_scope) == "request-1"
    assert len(server._request_id_from_scope({"headers": [(b"x-request-id", b"bad id")]})) == 32
    assert server._error_content("unknown", "r", details={"safe": True})["details"]["safe"]


@pytest.mark.parametrize(
    ("value", "schema", "fragment"),
    [
        (None, {"type": "object"}, "type must"),
        ({}, {"type": 7}, "invalid schema type"),
        ("x", {"enum": ["y"]}, "allowed enum"),
        ({}, {"type": "object", "required": ["a"]}, "required property"),
        (
            {"x": 1},
            {"type": "object", "properties": {}, "additionalProperties": False},
            "additional",
        ),
        ({}, {"type": "object", "properties": [], "minProperties": 1}, "invalid schema"),
        ({}, {"type": "object", "properties": {}, "minProperties": 1}, "too few"),
        ({"a": 1}, {"type": "object", "properties": {}, "maxProperties": 0}, "too many"),
        ([], {"type": "array", "minItems": 1}, "too few"),
        ([1], {"type": "array", "maxItems": 0}, "too many"),
        ("", {"type": "string", "minLength": 1}, "too short"),
        ("xx", {"type": "string", "maxLength": 1}, "too long"),
        (0, {"type": "number", "minimum": 1}, "below minimum"),
        (2, {"type": "number", "maximum": 1}, "above maximum"),
        (1, {"type": "number", "exclusiveMinimum": 1}, "exclusive minimum"),
        (1, {"type": "number", "exclusiveMaximum": 1}, "exclusive maximum"),
    ],
)
def test_json_schema_security_subset(value, schema, fragment):
    assert any(fragment in issue for issue in server._validate_json_schema(value, schema))


def test_json_schema_nested_and_type_matrix():
    for value, expected in [
        ({}, "object"),
        ([], "array"),
        ("x", "string"),
        (1, "integer"),
        (1.5, "number"),
        (True, "boolean"),
        (None, "null"),
    ]:
        assert server._matches_json_type(value, expected)
    assert not server._matches_json_type(object(), "unknown")
    schema = {
        "type": "object",
        "properties": {"items": {"type": "array", "items": {"type": "integer"}}},
        "additionalProperties": {"type": "string"},
    }
    assert server._validate_json_schema({"items": [1, 2], "label": "ok"}, schema) == []
    deep = {"type": "object", "properties": {"a": {"type": "object"}}}
    assert "depth" in server._validate_json_schema({}, deep, depth=server._MAX_SCHEMA_DEPTH + 1)[0]
    issues = ["existing"] * 20
    assert server._validate_json_schema({}, {}, issues=issues) is issues


def test_json_schema_enforces_published_anyof_const_pattern_format_and_uniqueness():
    assert (
        server._validate_json_schema(None, {"anyOf": [{"type": "string"}, {"type": "null"}]}) == []
    )
    assert (
        server._validate_json_schema("value", {"anyOf": [{"type": "string"}, {"type": "null"}]})
        == []
    )
    invalid_cases = [
        (7, {"anyOf": [{"type": "string"}, {"type": "null"}]}),
        (False, {"const": True}),
        ("Invalid Slug", mcp_schemas.SLUG_SCHEMA),
        ("bad key!", mcp_schemas.IDEMPOTENCY_SCHEMA),
        ("not-a-uuid", mcp_schemas.UUID_SCHEMA),
        ("2026-99-99T25:61:00Z", {"type": "string", "format": "date-time"}),
        ("javascript:alert(1)", {"type": "string", "format": "uri"}),
        ("https://user@example.com/repo", {"type": "string", "format": "uri"}),
        ("https://example.com/repo#fragment", {"type": "string", "format": "uri"}),
        ([{"a": 1, "b": 2}, {"b": 2, "a": 1}], {"type": "array", "uniqueItems": True}),
    ]
    for value, schema in invalid_cases:
        assert server._validate_json_schema(value, schema)

    for value, format_name in [
        ("11111111-1111-4111-8111-111111111111", "uuid"),
        ("2026-07-20T12:30:00Z", "date-time"),
        ("https://github.com/dataforalltech/platform-devs?tab=readme", "uri"),
    ]:
        assert server._validate_json_schema(value, {"type": "string", "format": format_name}) == []


def test_json_schema_issues_never_include_rejected_values():
    rejected = "do-not-leak-this-value"
    issues = server._validate_json_schema(
        rejected,
        {"type": "string", "pattern": "^[0-9]+$"},
    )
    assert issues
    assert rejected not in " ".join(issues)


@pytest.mark.parametrize(
    "web_url",
    [
        "javascript:alert(1)",
        "file:///tmp/repository",
        "https://user@example.com/repository",
        "https://example.com/repository#fragment",
        "https://example.com\\repository",
        "http://",
    ],
)
def test_repository_metadata_web_url_rejects_non_http_or_unsafe_uris(web_url):
    schema = mcp_schemas.REPOSITORY_METADATA_SCHEMA["properties"]["web_url"]
    assert server._validate_json_schema(web_url, schema)


def test_repository_metadata_web_url_accepts_safe_http_uri_and_null():
    schema = mcp_schemas.REPOSITORY_METADATA_SCHEMA["properties"]["web_url"]
    assert (
        server._validate_json_schema(
            "https://github.com/dataforalltech/platform-devs?tab=readme", schema
        )
        == []
    )
    assert server._validate_json_schema(None, schema) == []


@pytest.mark.parametrize(
    "invalid",
    [
        [],
        {"params": []},
        {"params": {"name": ""}},
        {"params": {"name": "x", "arguments": []}},
        {"params": {"name": "x", "_meta": []}},
    ],
)
def test_call_envelope_rejects_invalid_shapes(invalid):
    with pytest.raises(server.InvalidMcpEnvelopeError):
        server._parse_call_envelope(invalid)


def test_call_envelope_normalizes_optional_fields():
    assert server._parse_call_envelope({"name": "x", "arguments": None, "_meta": None}) == (
        "x",
        {},
        {},
    )


@pytest.mark.asyncio
async def test_inner_token_verification_all_claim_guards(monkeypatch):
    settings = server.get_settings()
    signing_key = SimpleNamespace(key="public")
    resolver = SimpleNamespace(get_signing_key_from_jwt=lambda _token: signing_key)
    monkeypatch.setattr(server.jwt, "get_unverified_header", lambda _token: {"alg": "RS256"})

    current = claims()
    monkeypatch.setattr(server.jwt, "decode", lambda *_args, **_kwargs: dict(current))
    result = await server._verify_inner_token("token", settings, resolver, asyncio.Semaphore(1))
    assert result["tenant_id"] == TENANT

    cases = [
        ({"iat": "bad"}, server.InvalidInnerTokenClaimsError),
        ({"exp": 200}, server.InvalidInnerTokenClaimsError),
        ({"jti": ""}, server.JtiRequiredError),
        ({"parent_jti": ""}, server.InvalidInnerTokenClaimsError),
        ({"sub": ""}, server.InvalidInnerTokenClaimsError),
        ({"tenant_id": "../tenant"}, server.InvalidTenantScopeError),
        ({"scopes": "read"}, server.InvalidInnerTokenClaimsError),
    ]
    for changes, expected in cases:
        current = claims()
        current.update(changes)
        with pytest.raises(expected):
            await server._verify_inner_token("token", settings, resolver, asyncio.Semaphore(1))

    monkeypatch.setattr(server.jwt, "get_unverified_header", lambda _token: {"alg": "HS256"})
    with pytest.raises(server.InvalidInnerTokenClaimsError, match="algorithm"):
        await server._verify_inner_token("token", settings, resolver, asyncio.Semaphore(1))


@pytest.mark.parametrize(
    ("headers", "claim_changes", "expected"),
    [
        ({}, {}, None),
        ({}, {"sub": "7"}, None),
        ({"X-Environment-Id": "32767"}, {}, None),
        (
            {"X-Execution-Depth": "xxxx"},
            {},
            server.InvalidExecutionContextError,
        ),
        (
            {"X-Execution-Depth": "x"},
            {},
            server.InvalidExecutionContextError,
        ),
        (
            {"X-Execution-Depth": "-1"},
            {},
            server.InvalidExecutionContextError,
        ),
        ({"X-Execution-Depth": "8"}, {}, OverflowError),
        ({}, {"sub": "agent:7"}, server.InvalidExecutionContextError),
        ({}, {"sub": "0"}, server.InvalidExecutionContextError),
        ({}, {"tenant_id": "tenant-with-hyphen"}, server.InvalidTenantScopeError),
        ({}, {"tenant_id": "1tenant"}, server.InvalidTenantScopeError),
        ({}, {"tenant_id": "a" * 101}, server.InvalidTenantScopeError),
        ({}, {"tenant_id": "../bad"}, server.InvalidTenantScopeError),
    ],
)
def test_trusted_context_guards(headers, claim_changes, expected):
    token_claims = claims()
    token_claims.update(claim_changes)
    if expected is None:
        context = server._trusted_context_from_claims(request(headers), token_claims)
        assert context.execution_depth == 1
        assert token_claims["_environment_id"] == 0
        assert token_claims["_actor_id"] == 7
        assert context.environment_id == 0
        assert context.actor_id == 7
    else:
        with pytest.raises(expected):
            server._trusted_context_from_claims(request(headers), token_claims)


@pytest.mark.asyncio
async def test_dispatch_registry_covers_sync_async_and_rejections(monkeypatch):
    context = TrustedMcpContext(TENANT, 7, 0, "r", 1)
    client = object()

    async def async_handler(_client, args, _context):
        return {"name": args["name"]}

    def sync_handler(_client, args, _context):
        return {"name": args["name"]}

    names = list(server._TOOL_SCHEMAS)
    for index, name in enumerate(names):
        monkeypatch.setattr(server, name, async_handler if index % 2 else sync_handler)
    for name in names:
        assert (await server._dispatch(name, {"name": name}, client, context))["name"] == name
    with pytest.raises(PermissionError):
        await server._dispatch(names[0], {}, client, None)
    with pytest.raises(KeyError):
        await server._dispatch("unknown", {}, client, context)


def test_http_sidecar_error_matrix(monkeypatch):
    monkeypatch.setattr(server, "_verify_inner_token", verified)

    async def api_ready(_client):
        return None

    monkeypatch.setattr(server.ServiceApiClient, "readiness", api_ready)
    rate = MutableRateStore()
    policy = MutablePolicy()

    async def ok(*_args, **_kwargs):
        return product_result()

    monkeypatch.setattr(server, "_dispatch", ok)
    jwks = SimpleNamespace(get_signing_keys=lambda *, refresh: [refresh])
    app = server.build_server(policy, rate_limit_store=rate, jwks_client=jwks)[2]
    with TestClient(app) as client:
        assert client.get("/v1/health").json() == {"status": "ok"}
        assert client.get("/v1/ready").json()["status"] == "ready"
        policy.error = True
        not_ready = client.get("/v1/ready")
        assert not_ready.status_code == 503
        assert not_ready.json()["checks"]["governance"] == "unavailable"
        policy.error = False
        assert client.post("/mcp/tools/call", json=[]).status_code == 400
        assert (
            client.post(
                "/mcp/tools/call",
                json={"params": {"name": "unknown", "arguments": {}}},
            ).status_code
            == 404
        )

        monkeypatch.setattr(server, "_EXCLUDE_TOOLS", {"product_get"})
        assert len(client.get("/mcp/tools/list").json()["result"]["tools"]) == 12
        assert client.post("/mcp/tools/call", json=body()).status_code == 403
        monkeypatch.setattr(server, "_EXCLUDE_TOOLS", frozenset())

        assert client.post("/mcp/tools/call", json=body(None)).status_code == 401
        assert (
            client.post(
                "/mcp/tools/call",
                json=body(None),
                headers={"Authorization": "Bearer token"},
            ).status_code
            == 200
        )

        rate.allowed = False
        assert client.get("/mcp/tools/list").status_code == 429
        rate.allowed = True
        rate.error = True
        assert client.get("/mcp/tools/list").status_code == 503
        rate.error = False

        policy.error = True
        assert (
            client.post(
                "/mcp/tools/call",
                json=body(),
                headers={"X-Environment-Id": "2"},
            ).status_code
            == 503
        )
        policy.error = False
        policy.decision = server.PolicyDecision("pending")
        assert (
            client.post(
                "/mcp/tools/call",
                json=body(),
                headers={"X-Environment-Id": "2"},
            ).status_code
            == 503
        )
        policy.decision = server.PolicyDecision("deny")
        assert (
            client.post(
                "/mcp/tools/call",
                json=body(),
                headers={"X-Environment-Id": "2"},
            ).status_code
            == 403
        )
        policy.decision = server.PolicyDecision("allow")

        errors = [
            (AdapterUnavailableError("down"), 504, "backend_unreachable"),
            (AdapterResponseError(504), 504, "backend_unreachable"),
            (AdapterResponseError(500), 500, "adapter_server_error"),
            (AdapterResponseError(409), 409, "adapter_rejected"),
            (server.InvalidToolResponseError("malformed"), 502, "invalid_tool_response"),
            (KeyError("missing"), 500, "tool_execution_failed"),
            (PermissionError("denied"), 403, "policy_denied"),
            (RuntimeError("boom"), 500, "tool_execution_failed"),
        ]
        for error, expected_status, expected_code in errors:

            async def fail(*_args, current=error, **_kwargs):
                raise current

            monkeypatch.setattr(server, "_dispatch", fail)
            response = client.post(
                "/mcp/tools/call",
                json=body(),
                headers={"X-Environment-Id": "2"},
            )
            assert response.status_code == expected_status
            assert response.json()["error"] == expected_code

        monkeypatch.setattr(server, "_dispatch", ok)
        settings = server.get_settings()
        original_size = settings.MCP_MAX_RESPONSE_BODY_BYTES
        settings.MCP_MAX_RESPONSE_BODY_BYTES = 8
        assert (
            client.post(
                "/mcp/tools/call",
                json=body(),
                headers={"X-Environment-Id": "2"},
            ).status_code
            == 502
        )
        settings.MCP_MAX_RESPONSE_BODY_BYTES = original_size

    assert rate.started == 1 and rate.closed == 1 and policy.closed == 1


@pytest.mark.asyncio
async def test_security_middleware_content_length_and_stream_limits():
    called = 0

    async def app(_scope, receive, send):
        nonlocal called
        called += 1
        await receive()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    middleware = server.McpHttpSecurityMiddleware(app, max_body_bytes=4)

    async def run(headers, messages):
        sent = []

        async def receive():
            return messages.pop(0)

        async def send(message):
            sent.append(message)

        scope = {
            "type": "http",
            "method": "POST",
            "path": "/mcp/tools/call",
            "scheme": "https",
            "headers": headers,
        }
        await middleware(scope, receive, send)
        return sent

    invalid = await run([(b"content-length", b"x")], [{"type": "http.request", "body": b""}])
    assert invalid[0]["status"] == 400
    large = await run([(b"content-length", b"5")], [{"type": "http.request", "body": b""}])
    assert large[0]["status"] == 413
    streamed = await run([], [{"type": "http.request", "body": b"12345"}])
    assert streamed[0]["status"] == 413
    ok = await run([(b"content-length", b"2")], [{"type": "http.request", "body": b"12"}])
    assert ok[0]["status"] == 200
    assert any(header[0] == b"strict-transport-security" for header in ok[0]["headers"])
    assert called == 2
