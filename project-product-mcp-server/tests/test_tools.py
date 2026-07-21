from __future__ import annotations

import pytest
from project_product_mcp.client.api_client import TrustedMcpContext

from project_product_mcp import tools
from project_product_mcp.server import mcp_server as server

CTX = TrustedMcpContext("11111111-1111-4111-8111-111111111111", 7, 2, "req-1", 1)


class FakeClient:
    def __init__(self):
        self.calls = []

    async def get(self, path, **kwargs):
        self.calls.append(("GET", path, kwargs))
        if path.endswith("/products") or path.endswith("/projects"):
            return {"items": [], "next_after_id": None}
        if path.endswith("/repositories"):
            return {"items": [], "next_after_id": None}
        return _record(path)

    async def post(self, path, **kwargs):
        self.calls.append(("POST", path, kwargs))
        return _record(path)

    async def patch(self, path, **kwargs):
        self.calls.append(("PATCH", path, kwargs))
        return _record(path)

    async def delete(self, path, **kwargs):
        self.calls.append(("DELETE", path, kwargs))
        if "/repositories/" in path:
            return {"binding_id": path.rsplit("/", 1)[-1], "detached": True}
        key = "product_id" if "/products/" in path else "project_id"
        return {key: path.rsplit("/", 1)[-1], "deleted": True}


def _record(path):
    base = {
        "version": 1,
        "is_active": True,
        "id_environment": 2,
        "id_owner": 7,
        "created_at": "2026-07-19T00:00:00Z",
        "updated_at": "2026-07-19T00:00:00Z",
        "created_by": 7,
        "updated_by": 7,
    }
    if "/repositories" in path:
        return {
            **base,
            "binding_id": "33333333-3333-4333-8333-333333333333",
            "project_id": "22222222-2222-4222-8222-222222222222",
            "provider": "github",
            "connector_ref": "connector:1",
            "repository_ref": "repo:1",
            "role": "source",
            "metadata": {},
        }
    if "/projects" in path:
        return {
            **base,
            "project_id": "22222222-2222-4222-8222-222222222222",
            "product_id": "11111111-1111-4111-8111-111111111111",
            "slug": "project",
            "name": "Project",
            "description": None,
            "status": "active",
            "owner_user_refs": [],
            "service_refs": {
                "governance_ref": None,
                "schedule_ref": None,
                "communication_ref": None,
                "notification_ref": None,
            },
        }
    return {
        **base,
        "product_id": "11111111-1111-4111-8111-111111111111",
        "slug": "product",
        "name": "Product",
        "description": None,
        "status": "active",
        "owner_user_refs": [],
    }


def test_nullable_rest_defaults_satisfy_mcp_input_and_output_contracts():
    product_input = {
        "idempotency_key": "product-1",
        "slug": "product",
        "name": "Product",
        "description": None,
    }
    project_input = {
        "idempotency_key": "project-1",
        "product_id": "11111111-1111-4111-8111-111111111111",
        "slug": "project",
        "name": "Project",
        "description": None,
        "service_refs": {
            "governance_ref": None,
            "schedule_ref": None,
            "communication_ref": None,
            "notification_ref": None,
        },
    }
    assert server._validate_json_schema(product_input, server.PRODUCT_CREATE_INPUT) == []
    assert server._validate_json_schema(project_input, server.PROJECT_CREATE_INPUT) == []

    product = tools._public(_record("/products/id"))
    project = tools._public(_record("/projects/id"))
    repository_record = _record("/repositories/id")
    repository_record["metadata"] = {
        "display_name": None,
        "default_branch": None,
        "web_url": None,
    }
    repository = tools._public(repository_record)
    assert server._validate_json_schema(product, server.PRODUCT_SCHEMA) == []
    assert server._validate_json_schema(project, server.PROJECT_SCHEMA) == []
    assert server._validate_json_schema(repository, server.REPOSITORY_BINDING_SCHEMA) == []


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"items": []},
        {"next_after_id": None},
        {"items": "not-a-list", "next_after_id": None},
        {"items": [], "next_after_id": 7},
        {"items": [{}], "next_after_id": None},
    ],
)
def test_page_rejects_missing_or_malformed_adapter_payload(payload):
    with pytest.raises(tools.InvalidToolResponseError):
        tools._page(payload)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"items": []},
        {"next_after_id": None},
        {"items": "not-a-list", "next_after_id": None},
        {"items": [], "next_after_id": 7},
        {"items": [{}], "next_after_id": None},
    ],
)
def test_repository_page_rejects_missing_or_malformed_adapter_payload(payload):
    with pytest.raises(tools.InvalidToolResponseError):
        tools._repository_page(payload)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"items": "not-a-list", "next_after_id": None},
        {"items": [{}], "next_after_id": None},
    ],
)
async def test_repository_list_propagates_malformed_adapter_payload(payload):
    class MalformedRepositoryPageClient:
        async def get(self, path, **kwargs):
            return payload

    with pytest.raises(tools.InvalidToolResponseError):
        await tools.project_repository_list(
            MalformedRepositoryPageClient(),
            {"project_id": "11111111-1111-4111-8111-111111111111"},
            CTX,
        )


@pytest.mark.asyncio
async def test_repository_list_forwards_cursor_and_returns_next_after_id():
    class Client:
        def __init__(self):
            self.params = None

        async def get(self, path, **kwargs):
            self.params = kwargs.get("params")
            return {"items": [], "next_after_id": "33333333-3333-4333-8333-333333333333"}

    client = Client()
    out = await tools.project_repository_list(
        client,
        {
            "project_id": "22222222-2222-4222-8222-222222222222",
            "after_id": "11111111-1111-4111-8111-111111111111",
            "limit": 10,
        },
        CTX,
    )
    assert out["next_after_id"] == "33333333-3333-4333-8333-333333333333"
    assert client.params["after_id"] == "11111111-1111-4111-8111-111111111111"
    assert client.params["limit"] == 10


def test_public_projection_rejects_missing_or_invalid_audit_fields():
    with pytest.raises(tools.InvalidToolResponseError):
        tools._public({})
    with pytest.raises(tools.InvalidToolResponseError):
        tools._public({"created_by": True, "updated_by": 7})


@pytest.mark.asyncio
async def test_all_tool_adapters_use_only_private_api_paths():
    client = FakeClient()
    product = "11111111-1111-4111-8111-111111111111"
    project = "22222222-2222-4222-8222-222222222222"
    binding = "33333333-3333-4333-8333-333333333333"
    await tools.product_create(
        client, {"idempotency_key": "product-1", "slug": "product", "name": "Product"}, CTX
    )
    await tools.product_get(client, {"product_id": product}, CTX)
    await tools.product_list(client, {}, CTX)
    await tools.product_update(
        client,
        {
            "product_id": product,
            "idempotency_key": "product-2",
            "expected_version": 1,
            "changes": {"name": "P2"},
        },
        CTX,
    )
    await tools.product_delete(
        client, {"product_id": product, "idempotency_key": "product-3", "expected_version": 2}, CTX
    )
    await tools.project_create(
        client,
        {
            "product_id": product,
            "idempotency_key": "project-1",
            "slug": "project",
            "name": "Project",
        },
        CTX,
    )
    await tools.project_get(client, {"project_id": project}, CTX)
    await tools.project_list(client, {}, CTX)
    await tools.project_update(
        client,
        {
            "project_id": project,
            "idempotency_key": "project-2",
            "expected_version": 1,
            "changes": {"name": "P2"},
        },
        CTX,
    )
    await tools.project_delete(
        client, {"project_id": project, "idempotency_key": "project-3", "expected_version": 2}, CTX
    )
    await tools.project_repository_attach(
        client,
        {
            "project_id": project,
            "idempotency_key": "binding-1",
            "provider": "github",
            "connector_ref": "connector:1",
            "repository_ref": "repo:1",
        },
        CTX,
    )
    await tools.project_repository_list(client, {"project_id": project}, CTX)
    await tools.project_repository_detach(
        client, {"binding_id": binding, "idempotency_key": "binding-2", "expected_version": 1}, CTX
    )
    assert len(client.calls) == 13
    assert all(path.startswith("/api/internal/mcp/") for _, path, _ in client.calls)
    assert all("tenant_id" not in kwargs.get("json", {}) for _, _, kwargs in client.calls)
    created = await tools.product_get(client, {"product_id": product}, CTX)
    assert created["created_by_ref"] == "platform-admin:user:7"
    assert "id_owner" not in created
