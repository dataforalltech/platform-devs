from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from app.modules.idempotency_repository import IdempotencyRepository
from app.modules.products.repository import ProductRepository
from app.modules.projects.repository import ProjectRepository
from app.modules.repository_bindings.repository import RepositoryBindingRepository

PRODUCT = UUID("11111111-1111-4111-8111-111111111111")
PROJECT = UUID("22222222-2222-4222-8222-222222222222")
BINDING = UUID("33333333-3333-4333-8333-333333333333")


class Result:
    def __init__(self, items=None):
        self.items = items or []

    def first(self):
        return self.items[0] if self.items else None

    def models(self):
        return self.items


def orm():
    repository = SimpleNamespace(
        find_one=AsyncMock(return_value="one"),
        find=AsyncMock(return_value=Result(["row"])),
        count=AsyncMock(return_value=1),
        insert=AsyncMock(return_value=SimpleNamespace(rowcount=1)),
        update_where=AsyncMock(return_value=SimpleNamespace(rowcount=1)),
        execute_query_object=AsyncMock(return_value=Result(["locked"])),
    )
    return repository


@pytest.mark.asyncio
async def test_product_repository_all_scoped_operations():
    raw = orm()
    repository = ProductRepository(raw)
    assert await repository.get(PRODUCT, 2, 7) == "one"
    assert await repository.get_writable(PRODUCT, 2, 7) == "one"
    assert await repository.get_writable_for_update(PRODUCT, 2, 7) == "locked"
    assert await repository.get_any(PRODUCT, 2, 7) == "row"
    assert await repository.get_any_for_update(PRODUCT, 2, 7) == "locked"
    assert await repository.by_idempotency("key", 2, 7) == "row"
    assert await repository.by_slug("slug", 2, 7) == "one"
    assert await repository.list(
        2,
        7,
        status="active",
        after_id=PRODUCT,
        limit=10,
    ) == ["row"]
    await repository.insert({"name": "Product"}, 7)
    await repository.update_scoped(PRODUCT, 2, 7, 1, {"name": "P2"}, 7)
    await repository.mark_deleted(PRODUCT, 2, 7, 2, {"is_deleted": True}, 7)
    assert raw.find.await_count == 3
    assert raw.update_where.await_count == 2


@pytest.mark.asyncio
async def test_project_repository_all_scoped_operations():
    raw = orm()
    repository = ProjectRepository(raw)
    assert await repository.get(PROJECT, 2, 7) == "one"
    assert await repository.get_writable(PROJECT, 2, 7) == "one"
    assert await repository.get_writable_for_update(PROJECT, 2, 7) == "locked"
    assert await repository.get_any(PROJECT, 2, 7) == "row"
    assert await repository.get_any_for_update(PROJECT, 2, 7) == "locked"
    assert await repository.by_idempotency("key", 2, 7) == "row"
    assert await repository.list(
        2,
        7,
        product_id=PRODUCT,
        status="active",
        after_id=PROJECT,
        limit=10,
    ) == ["row"]
    assert await repository.count_for_product(PRODUCT, 2, 7) == 1
    await repository.insert({"name": "Project"}, 7)
    await repository.update_scoped(PROJECT, 2, 7, 1, {"name": "P2"}, 7)
    raw.find.assert_awaited()
    raw.count.assert_awaited_once()


@pytest.mark.asyncio
async def test_binding_repository_all_scoped_operations():
    raw = orm()
    repository = RepositoryBindingRepository(raw)
    assert await repository.get(BINDING, 2, 7) == "one"
    assert await repository.get_any(BINDING, 2, 7) == "row"
    assert await repository.get_any_for_update(BINDING, 2, 7) == "locked"
    assert await repository.by_idempotency("key", 2, 7) == "row"
    assert await repository.list_for_project(
        PROJECT,
        2,
        7,
        provider="github",
        role="source",
    ) == ["row"]
    assert await repository.count_for_project(PROJECT, 2, 7) == 1
    await repository.insert({"provider": "github"}, 7)
    await repository.detach(PROJECT, BINDING, 2, 7, 1, {"is_deleted": True}, 7)
    raw.update_where.assert_awaited_once()


@pytest.mark.asyncio
async def test_idempotency_repository_binds_key_operation_and_hash():
    raw = orm()
    repository = IdempotencyRepository(raw)
    assert await repository.get("request-key", 0, 0) == "one"
    await repository.insert({"idempotency_key": "request-key"}, 7)
    await repository.complete(
        key="request-key",
        environment=0,
        owner=0,
        operation="product.create",
        request_hash="a" * 64,
        response_body={"product_id": str(PRODUCT)},
        updated_at=SimpleNamespace(),
        actor=7,
    )
    raw.find_one.assert_awaited_once()
    raw.insert.assert_awaited_once()
    raw.update_where.assert_awaited_once()
