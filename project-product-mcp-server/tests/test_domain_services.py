from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from platform_database.orm import UniqueViolationError

from app.core.context import ActorContext
from app.core.exceptions import ConflictError, NotFoundError
from app.core.idempotency import request_fingerprint
from app.core.repositories import PortfolioRepositories
from app.models import IdempotencyRecord, ProductRecord, ProjectRecord, RepositoryBindingRecord
from app.modules.products import mappers as product_mappers
from app.modules.products.services import ProductService
from app.modules.projects.services import ProjectService
from app.modules.repository_bindings.services import RepositoryBindingService
from platform_project_product.schemas import (
    ProductCreate,
    ProductUpdate,
    ProjectCreate,
    ProjectUpdate,
    RepositoryBindingCreate,
)

ACTOR = ActorContext(actor_id=7, environment_id=0, request_id="req-1")
NOW = datetime(2026, 7, 20, tzinfo=UTC)
PRODUCT_ID = UUID("11111111-1111-4111-8111-111111111111")
PROJECT_ID = UUID("22222222-2222-4222-8222-222222222222")
BINDING_ID = UUID("33333333-3333-4333-8333-333333333333")


def product(**changes) -> ProductRecord:
    values = dict(
        product_id=PRODUCT_ID,
        slug="product",
        name="Product",
        description=None,
        status="active",
        owner_user_refs=[],
        version=1,
        last_idempotency_key="product-key",
        id_environment=0,
        id_owner=0,
        created_at=NOW,
        updated_at=NOW,
        created_by=7,
        updated_by=7,
    )
    values.update(changes)
    return ProductRecord(**values)


def project(**changes) -> ProjectRecord:
    values = dict(
        project_id=PROJECT_ID,
        product_id=PRODUCT_ID,
        slug="project",
        name="Project",
        description=None,
        status="active",
        owner_user_refs=[],
        service_refs={},
        version=1,
        last_idempotency_key="project-key",
        id_environment=0,
        id_owner=0,
        created_at=NOW,
        updated_at=NOW,
        created_by=7,
        updated_by=7,
    )
    values.update(changes)
    return ProjectRecord(**values)


def binding(**changes) -> RepositoryBindingRecord:
    values = dict(
        binding_id=BINDING_ID,
        project_id=PROJECT_ID,
        provider="github",
        connector_ref="connector:1",
        repository_ref="repo:1",
        role="source",
        metadata={},
        version=1,
        last_idempotency_key="binding-key",
        id_environment=0,
        id_owner=0,
        created_at=NOW,
        updated_at=NOW,
        created_by=7,
        updated_by=7,
    )
    values.update(changes)
    return RepositoryBindingRecord(**values)


def ledger(
    *,
    key: str,
    operation: str,
    request_hash: str,
    target_type: str,
    target_id: UUID,
    response_body: dict | None = None,
) -> IdempotencyRecord:
    return IdempotencyRecord(
        id=1,
        id_environment=0,
        id_owner=0,
        idempotency_key=key,
        operation=operation,
        request_hash=request_hash,
        target_type=target_type,
        target_id=target_id,
        response_body=response_body or {},
        status="completed",
        created_at=NOW,
        updated_at=NOW,
        created_by=7,
        updated_by=7,
    )


def repositories(*, transaction_events: list[str] | None = None) -> PortfolioRepositories:
    products = SimpleNamespace(
        by_slug=AsyncMock(return_value=None),
        insert=AsyncMock(return_value=SimpleNamespace(rowcount=1)),
        get_writable=AsyncMock(return_value=product()),
        get_writable_for_update=AsyncMock(return_value=product()),
        get=AsyncMock(return_value=product()),
        get_any=AsyncMock(return_value=product()),
        get_any_for_update=AsyncMock(return_value=product()),
        update_scoped=AsyncMock(return_value=SimpleNamespace(rowcount=1)),
        mark_deleted=AsyncMock(return_value=SimpleNamespace(rowcount=1)),
        list=AsyncMock(return_value=[]),
    )
    projects = SimpleNamespace(
        count_for_product=AsyncMock(return_value=0),
        insert=AsyncMock(return_value=SimpleNamespace(rowcount=1)),
        get_writable=AsyncMock(return_value=project()),
        get_writable_for_update=AsyncMock(return_value=project()),
        get=AsyncMock(return_value=project()),
        get_any=AsyncMock(return_value=project()),
        get_any_for_update=AsyncMock(return_value=project()),
        update_scoped=AsyncMock(return_value=SimpleNamespace(rowcount=1)),
        list=AsyncMock(return_value=[]),
    )
    bindings = SimpleNamespace(
        count_for_project=AsyncMock(return_value=0),
        insert=AsyncMock(return_value=SimpleNamespace(rowcount=1)),
        get=AsyncMock(return_value=binding()),
        get_any=AsyncMock(return_value=binding()),
        get_any_for_update=AsyncMock(return_value=binding()),
        detach=AsyncMock(return_value=SimpleNamespace(rowcount=1)),
        list_for_project=AsyncMock(return_value=[]),
    )
    idempotency = SimpleNamespace(
        get=AsyncMock(return_value=None),
        insert=AsyncMock(return_value=SimpleNamespace(rowcount=1)),
        complete=AsyncMock(return_value=SimpleNamespace(rowcount=1)),
    )
    holder: dict[str, PortfolioRepositories] = {}

    @asynccontextmanager
    async def transaction():
        if transaction_events is not None:
            transaction_events.append("begin")
        try:
            yield holder["repositories"]
        finally:
            if transaction_events is not None:
                transaction_events.append("end")

    result = PortfolioRepositories(
        products=products,
        projects=projects,
        bindings=bindings,
        idempotency=idempotency,
        _transaction_factory=transaction,
    )
    holder["repositories"] = result
    return result


@pytest.mark.asyncio
async def test_product_create_is_tenant_global_and_audited():
    repos = repositories()
    result = await ProductService(repos, ACTOR).create(
        ProductCreate(idempotency_key="product-key", slug="product", name="Product")
    )

    assert result.product_id == PRODUCT_ID
    payload = repos.products.insert.await_args.args[0]
    assert payload["id_environment"] == 0
    assert payload["id_owner"] == 0
    assert payload["created_by"] == 7
    pending = repos.idempotency.insert.await_args.args[0]
    assert pending["operation"] == "product.create"
    assert len(pending["request_hash"]) == 64
    assert repos.idempotency.complete.await_args.kwargs["response_body"]["name"] == "Product"


@pytest.mark.asyncio
async def test_product_create_exact_replay_and_divergent_reuse_conflict():
    repos = repositories()
    data = ProductCreate(idempotency_key="product-key", slug="product", name="Product")
    fingerprint = request_fingerprint(
        "product.create",
        data.model_dump(exclude={"idempotency_key"}, mode="json"),
    )
    repos.idempotency.get.return_value = ledger(
        key=data.idempotency_key,
        operation="product.create",
        request_hash=fingerprint,
        target_type="product",
        target_id=PRODUCT_ID,
        response_body=product_mappers.to_response(product()).model_dump(mode="json"),
    )
    assert (await ProductService(repos, ACTOR).create(data)).product_id == PRODUCT_ID
    repos.products.insert.assert_not_awaited()

    repos.idempotency.get.return_value = ledger(
        key=data.idempotency_key,
        operation="product.create",
        request_hash="0" * 64,
        target_type="product",
        target_id=PRODUCT_ID,
    )
    with pytest.raises(ConflictError, match="different request"):
        await ProductService(repos, ACTOR).create(data)


@pytest.mark.asyncio
async def test_concurrent_idempotency_unique_race_replays_committed_response():
    repos = repositories()
    data = ProductCreate(idempotency_key="product-key", slug="product", name="Product")
    fingerprint = request_fingerprint(
        "product.create",
        data.model_dump(exclude={"idempotency_key"}, mode="json"),
    )
    committed = ledger(
        key=data.idempotency_key,
        operation="product.create",
        request_hash=fingerprint,
        target_type="product",
        target_id=PRODUCT_ID,
        response_body=product_mappers.to_response(product()).model_dump(mode="json"),
    )
    repos.idempotency.get.side_effect = [None, committed]
    repos.idempotency.insert.side_effect = UniqueViolationError()

    response = await ProductService(repos, ACTOR).create(data)
    assert response.product_id == PRODUCT_ID
    repos.products.insert.assert_not_awaited()


@pytest.mark.asyncio
async def test_product_update_locks_row_and_records_exact_response():
    events: list[str] = []
    repos = repositories(transaction_events=events)
    repos.products.get_writable_for_update.return_value = product()
    repos.products.get.return_value = product(version=2, name="Changed")

    response = await ProductService(repos, ACTOR).update(
        PRODUCT_ID,
        ProductUpdate(idempotency_key="update-key", expected_version=1, name="Changed"),
    )

    assert response.version == 2
    assert events == ["begin", "end"]
    repos.products.get_writable_for_update.assert_awaited_once_with(PRODUCT_ID, 0, 0)
    assert repos.products.update_scoped.await_args.args[1:3] == (0, 0)


@pytest.mark.asyncio
async def test_product_update_version_and_observability_fail_closed():
    repos = repositories()
    repos.products.get_writable_for_update.return_value = product(version=2)
    with pytest.raises(ConflictError, match="version"):
        await ProductService(repos, ACTOR).update(
            PRODUCT_ID,
            ProductUpdate(idempotency_key="update-key", expected_version=1, name="Changed"),
        )

    repos = repositories()
    repos.products.get_writable_for_update.return_value = None
    with pytest.raises(NotFoundError):
        await ProductService(repos, ACTOR).update(
            PRODUCT_ID,
            ProductUpdate(idempotency_key="update-key", expected_version=1, name="Changed"),
        )


@pytest.mark.asyncio
async def test_product_delete_locks_parent_before_child_guard():
    repos = repositories()
    repos.projects.count_for_product.return_value = 1
    with pytest.raises(ConflictError, match="active projects"):
        await ProductService(repos, ACTOR).delete(
            PRODUCT_ID,
            expected_version=1,
            idempotency_key="delete-key",
        )
    repos.products.get_any_for_update.assert_awaited_once_with(PRODUCT_ID, 0, 0)
    repos.products.mark_deleted.assert_not_awaited()


@pytest.mark.asyncio
async def test_product_delete_exact_replay_does_not_mutate_again():
    repos = repositories()
    fingerprint = request_fingerprint(
        "product.delete",
        {"product_id": PRODUCT_ID, "expected_version": 1},
    )
    repos.idempotency.get.return_value = ledger(
        key="delete-key",
        operation="product.delete",
        request_hash=fingerprint,
        target_type="product",
        target_id=PRODUCT_ID,
    )
    await ProductService(repos, ACTOR).delete(
        PRODUCT_ID,
        expected_version=1,
        idempotency_key="delete-key",
    )
    repos.products.mark_deleted.assert_not_awaited()


@pytest.mark.asyncio
async def test_project_create_locks_live_product_and_is_tenant_global():
    repos = repositories()
    response = await ProjectService(repos, ACTOR).create(
        ProjectCreate(
            idempotency_key="project-key",
            product_id=PRODUCT_ID,
            slug="project",
            name="Project",
        )
    )
    assert response.project_id == PROJECT_ID
    repos.products.get_writable_for_update.assert_awaited_once_with(PRODUCT_ID, 0, 0)
    payload = repos.projects.insert.await_args.args[0]
    assert payload["id_environment"] == payload["id_owner"] == 0
    assert payload["created_by"] == 7


@pytest.mark.asyncio
async def test_project_create_rejects_deleted_or_missing_parent():
    repos = repositories()
    repos.products.get_writable_for_update.return_value = None
    with pytest.raises(NotFoundError, match="Parent product"):
        await ProjectService(repos, ACTOR).create(
            ProjectCreate(
                idempotency_key="project-key",
                product_id=PRODUCT_ID,
                slug="project",
                name="Project",
            )
        )
    repos.projects.insert.assert_not_awaited()


@pytest.mark.asyncio
async def test_project_update_and_delete_use_locked_rows():
    repos = repositories()
    repos.projects.get.return_value = project(version=2, name="Changed")
    updated = await ProjectService(repos, ACTOR).update(
        PROJECT_ID,
        ProjectUpdate(idempotency_key="update-key", expected_version=1, name="Changed"),
    )
    assert updated.version == 2
    repos.projects.get_writable_for_update.assert_awaited_once_with(PROJECT_ID, 0, 0)

    repos = repositories()
    repos.bindings.count_for_project.return_value = 1
    with pytest.raises(ConflictError, match="bindings"):
        await ProjectService(repos, ACTOR).delete(
            PROJECT_ID,
            expected_version=1,
            idempotency_key="delete-key",
        )
    repos.projects.get_any_for_update.assert_awaited_once_with(PROJECT_ID, 0, 0)


@pytest.mark.asyncio
async def test_binding_attach_locks_project_and_detach_locks_binding():
    repos = repositories()
    response = await RepositoryBindingService(repos, ACTOR).attach(
        PROJECT_ID,
        RepositoryBindingCreate(
            idempotency_key="binding-key",
            provider="github",
            connector_ref="connector:1",
            repository_ref="repo:1",
        ),
    )
    assert response.binding_id == BINDING_ID
    repos.projects.get_writable_for_update.assert_awaited_once_with(PROJECT_ID, 0, 0)

    repos = repositories()
    await RepositoryBindingService(repos, ACTOR).detach(
        PROJECT_ID,
        BINDING_ID,
        expected_version=1,
        idempotency_key="detach-key",
    )
    repos.bindings.get_any_for_update.assert_awaited_once_with(BINDING_ID, 0, 0)
    repos.bindings.detach.assert_awaited_once()


@pytest.mark.asyncio
async def test_binding_attach_and_detach_fail_closed():
    repos = repositories()
    repos.projects.get_writable_for_update.return_value = None
    with pytest.raises(NotFoundError):
        await RepositoryBindingService(repos, ACTOR).attach(
            PROJECT_ID,
            RepositoryBindingCreate(
                idempotency_key="binding-key",
                provider="github",
                connector_ref="connector:1",
                repository_ref="repo:1",
            ),
        )

    repos = repositories()
    repos.bindings.get_any_for_update.return_value = binding(
        project_id=UUID("44444444-4444-4444-8444-444444444444")
    )
    with pytest.raises(NotFoundError):
        await RepositoryBindingService(repos, ACTOR).detach(
            PROJECT_ID,
            BINDING_ID,
            expected_version=1,
            idempotency_key="detach-key",
        )


@pytest.mark.asyncio
async def test_read_paths_are_shared_for_all_authenticated_tenant_members():
    repos = repositories()
    other_actor = ActorContext(actor_id=99, environment_id=0, request_id="other")
    repos.products.list.return_value = [product(created_by=7, updated_by=7)]
    rows, _ = await ProductService(repos, other_actor).list(
        status=None,
        after_id=None,
        limit=10,
    )
    assert [item.product_id for item in rows] == [PRODUCT_ID]
    repos.products.list.assert_awaited_once_with(0, 0, status=None, after_id=None, limit=11)


def test_canonical_fingerprint_is_stable_and_operation_bound():
    left = request_fingerprint("product.update", {"b": 2, "a": 1})
    right = request_fingerprint("product.update", {"a": 1, "b": 2})
    assert left == right
    assert left != request_fingerprint("product.create", {"a": 1, "b": 2})
    assert left != request_fingerprint("product.update", {"a": 1, "b": 3})
