from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient
from platform_core.request_context import reset_tenant_id, set_tenant_id

from app.api import health
from app.core import context, database, dependencies, security
from app.core.context import ActorContext
from app.core.repositories import PortfolioRepositories


def make_request(
    *,
    headers: dict[str, str] | None = None,
    state: dict | None = None,
) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [
                (name.lower().encode("ascii"), value.encode("ascii"))
                for name, value in (headers or {}).items()
            ],
            "state": state or {},
        }
    )


@pytest.mark.parametrize("value", [None, "x", 0, -1])
def test_actor_rejects_invalid_values(value):
    with pytest.raises(HTTPException):
        context._positive_actor(value)


def test_actor_context_rejects_non_global_environment():
    with pytest.raises(ValueError, match="tenant-global"):
        ActorContext(7, 1, None)


def test_public_and_internal_actor_contexts_are_strict():
    request = make_request(
        headers={"X-Environment-Id": "32767"},
        state={
            "jwt_claims": {"sub": "7"},
            "request_id": "request-1",
        },
    )
    assert context.public_actor_context(request) == ActorContext(7, 0, "request-1")
    assert context.public_actor_context(request).owner_id == 0
    assert context.internal_actor_context(make_request(), "7") == ActorContext(7, 0, None)

    failures = [make_request(), make_request(state={"jwt_claims": {"sub": "agent:x"}})]
    for item in failures:
        with pytest.raises(HTTPException):
            context.public_actor_context(item)


def test_tenant_binding_scope_and_internal_auth(monkeypatch):
    request = make_request(state={})
    token = set_tenant_id("tenant-1")
    try:
        claims = {
            "type": "access",
            "tenant_id": "tenant-1",
            "role": "editor",
            "roles": ["EDITOR"],
            "sub": "7",
        }
        monkeypatch.setattr(security, "decode_token", lambda raw: claims)
        assert security.bind_authenticated_claims(request, "raw-token") is claims
        assert security.require_portfolio_access("read")(request) is claims
        assert security.require_portfolio_access("write")(request) is claims
        with pytest.raises(HTTPException) as denied:
            security.require_portfolio_access("delete")(request)
        assert denied.value.status_code == 403

        for malformed in ({}, {"role": "unknown"}, {"roles": ["*"]}):
            with pytest.raises(HTTPException) as role_denied:
                security.require_portfolio_access("read")(
                    make_request(state={"jwt_claims": malformed})
                )
            assert role_denied.value.status_code == 403
        with pytest.raises(HTTPException):
            security.require_portfolio_access("read")(make_request())

        monkeypatch.setattr(
            security,
            "decode_token",
            lambda raw: {**claims, "tenant_id": "other"},
        )
        with pytest.raises(HTTPException):
            security.bind_authenticated_claims(make_request(), "raw-token")

        monkeypatch.setattr(
            security,
            "decode_token",
            lambda raw: {**claims, "type": "service"},
        )
        with pytest.raises(HTTPException) as wrong_type:
            security.bind_authenticated_claims(make_request(), "raw-token")
        assert wrong_type.value.status_code == 401
    finally:
        reset_tenant_id(token)

    monkeypatch.setattr(
        security,
        "decode_token",
        lambda raw: {"type": "access", "tenant_id": "tenant-1"},
    )
    with pytest.raises(HTTPException):
        security.bind_authenticated_claims(make_request(), "raw-token")

    configured = security.settings.INTERNAL_API_TOKEN
    security.require_internal_token(configured.get_secret_value())
    with pytest.raises(HTTPException) as invalid:
        security.require_internal_token("wrong")
    assert invalid.value.status_code == 401
    monkeypatch.setattr(security.settings, "INTERNAL_API_TOKEN", None)
    with pytest.raises(HTTPException) as unavailable:
        security.require_internal_token("anything")
    assert unavailable.value.status_code == 503


@pytest.mark.asyncio
async def test_repository_dependency_uses_only_trusted_tenant(monkeypatch):
    expected = PortfolioRepositories(
        products=object(),
        projects=object(),
        bindings=object(),
        idempotency=object(),
    )

    @asynccontextmanager
    async def fake_bundle(tenant_id):
        assert tenant_id == "tenant-1"
        yield expected

    monkeypatch.setattr(dependencies, "portfolio_repositories", fake_bundle)
    token = set_tenant_id("tenant-1")
    try:
        generator = dependencies.get_portfolio_repositories()
        assert await anext(generator) is expected
        with pytest.raises(StopAsyncIteration):
            await anext(generator)
    finally:
        reset_tenant_id(token)

    generator = dependencies.get_portfolio_repositories()
    with pytest.raises(HTTPException):
        await anext(generator)


@pytest.mark.asyncio
async def test_database_lifecycle_delegates_to_approved_library(monkeypatch):
    configure = Mock()
    close = AsyncMock()
    monkeypatch.setattr(database, "configure", lambda settings: configure(settings))
    monkeypatch.setattr(database, "close_tenant_pools", close)
    database.configure_database()
    configure.assert_called_once_with(database.settings)
    await database.close_database()
    close.assert_awaited_once()


@pytest.mark.asyncio
async def test_readiness_reports_real_dependency_state(monkeypatch):
    pool = SimpleNamespace(fetchval=AsyncMock(side_effect=[1, 4]))

    async def available(*_args, **_kwargs):
        return pool

    monkeypatch.setattr(health, "get_pool_for_tenant", available)
    result = await health.readiness()
    assert result.status == "ok"
    assert pool.fetchval.await_args_list[0].args == ("SELECT 1",)
    schema_call = pool.fetchval.await_args_list[1]
    assert "information_schema.tables" in schema_call.args[0]
    assert schema_call.args[1:] == health._SCHEMA_CHECKS[health.settings.DB_ENGINE][1]

    missing_schema_pool = SimpleNamespace(fetchval=AsyncMock(side_effect=[1, 3]))

    async def missing_schema(*_args, **_kwargs):
        return missing_schema_pool

    monkeypatch.setattr(health, "get_pool_for_tenant", missing_schema)
    with pytest.raises(HTTPException) as missing:
        await health.readiness()
    assert missing.value.status_code == 503
    assert missing.value.detail["tenant_database"] == "schema_missing"

    async def unavailable(*_args, **_kwargs):
        raise OSError("registry down")

    monkeypatch.setattr(health, "get_pool_for_tenant", unavailable)
    with pytest.raises(HTTPException) as exc:
        await health.readiness()
    assert exc.value.status_code == 503
    assert exc.value.detail["tenant_database"] == "error"


def test_main_runtime_private_management_and_security_headers(monkeypatch):
    from app import main as runtime

    with TestClient(runtime.management_app) as client:
        assert client.get("/health/live").json() == {"status": "ok"}
        assert client.get("/metrics").status_code == 401
        assert (
            client.get(
                "/metrics",
                headers={
                    "Authorization": "Bearer metrics-test-token",
                    "X-Correlation-Id": "request-1",
                },
            ).status_code
            == 404
        )

    with TestClient(runtime.app) as client:
        response = client.post("/", content=b"x" * (runtime.settings.MAX_REQUEST_SIZE_BYTES + 1))
        assert response.status_code == 413
        ordinary = client.get("/")
        assert ordinary.headers["X-Content-Type-Options"] == "nosniff"


@pytest.mark.asyncio
async def test_serve_constructs_both_uvicorn_surfaces(monkeypatch):
    from app import main as runtime

    created = []

    class Config:
        def __init__(self, app, **kwargs):
            self.app = app
            self.kwargs = kwargs

    class Server:
        def __init__(self, config):
            created.append(config)

        async def serve(self):
            return None

    monkeypatch.setitem(sys.modules, "uvicorn", SimpleNamespace(Config=Config, Server=Server))
    await runtime.serve()
    assert {item.kwargs["port"] for item in created} == {
        runtime.settings.API_PORT,
        runtime.settings.HEALTH_PORT,
    }

    called = []
    monkeypatch.setattr(
        runtime.asyncio, "run", lambda coroutine: (called.append(coroutine), coroutine.close())
    )
    runtime.main()
    assert len(called) == 1
