"""Product domain rules with transactional, payload-bound idempotency."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from platform_core.base_service import BaseService
from platform_database.orm import UniqueViolationError

from app.core.context import ActorContext
from app.core.exceptions import ConflictError, NotFoundError
from app.core.idempotency import (
    assert_same_request,
    pending_record,
    replay_response,
    request_fingerprint,
)
from app.core.repositories import PortfolioRepositories
from app.modules.products import mappers
from platform_project_product.schemas import ProductCreate, ProductResponse, ProductUpdate

_TARGET = "product"


class ProductService(BaseService[dict, str]):
    def __init__(self, repositories: PortfolioRepositories, actor: ActorContext):
        super().__init__(id_user_ops=actor.actor_id, request_id=actor.request_id)
        self.repositories = repositories
        self.actor = actor

    async def _replay(
        self,
        key: str,
        operation: str,
        request_hash: str,
    ) -> ProductResponse | None:
        record = await self.repositories.idempotency.get(
            key,
            self.actor.environment_id,
            self.actor.owner_id,
        )
        if record is None:
            return None
        return replay_response(
            record,
            operation=operation,
            request_hash=request_hash,
            target_type=_TARGET,
            response_model=ProductResponse,
        )

    async def create(self, data: ProductCreate) -> ProductResponse:
        operation = "product.create"
        request_hash = request_fingerprint(
            operation,
            data.model_dump(exclude={"idempotency_key"}, mode="json"),
        )
        replay = await self._replay(data.idempotency_key, operation, request_hash)
        if replay is not None:
            return replay

        product_id = uuid4()
        try:
            async with self.repositories.transaction() as repositories:
                now = datetime.now(UTC)
                await repositories.idempotency.insert(
                    pending_record(
                        key=data.idempotency_key,
                        operation=operation,
                        request_hash=request_hash,
                        target_type=_TARGET,
                        target_id=product_id,
                        environment=self.actor.environment_id,
                        owner=self.actor.owner_id,
                        actor=self.actor.actor_id,
                        now=now,
                    ),
                    self.actor.actor_id,
                )
                if await repositories.products.by_slug(
                    data.slug,
                    self.actor.environment_id,
                    self.actor.owner_id,
                ):
                    raise ConflictError("Product slug already exists in the tenant")
                payload = {
                    **data.model_dump(exclude={"idempotency_key"}),
                    "product_id": product_id,
                    "last_idempotency_key": data.idempotency_key,
                    "version": 1,
                    "id_environment": self.actor.environment_id,
                    "id_owner": self.actor.owner_id,
                    "created_by": self.actor.actor_id,
                    "updated_by": self.actor.actor_id,
                    "created_at": now,
                    "updated_at": now,
                    "is_active": True,
                    "is_deleted": False,
                }
                await repositories.products.insert(payload, self.actor.actor_id)
                created = await repositories.products.get_writable(
                    product_id,
                    self.actor.environment_id,
                    self.actor.owner_id,
                )
                if created is None:
                    raise RuntimeError("Created product was not observable")
                response = mappers.to_response(created)
                completed = await repositories.idempotency.complete(
                    key=data.idempotency_key,
                    environment=self.actor.environment_id,
                    owner=self.actor.owner_id,
                    operation=operation,
                    request_hash=request_hash,
                    response_body=response.model_dump(mode="json"),
                    updated_at=datetime.now(UTC),
                    actor=self.actor.actor_id,
                )
                if completed.rowcount != 1:
                    raise RuntimeError("Idempotency ledger completion was not observable")
                return response
        except UniqueViolationError as exc:
            replay = await self._replay(data.idempotency_key, operation, request_hash)
            if replay is not None:
                return replay
            raise ConflictError("Product conflicts with an existing record") from exc

    async def get(self, product_id: UUID) -> ProductResponse:
        record = await self.repositories.products.get(
            product_id,
            self.actor.environment_id,
            self.actor.owner_id,
        )
        if record is None:
            raise NotFoundError("Product not found")
        return mappers.to_response(record)

    async def list(
        self, *, status: str | None, after_id: UUID | None, limit: int
    ) -> tuple[list[ProductResponse], UUID | None]:
        records = await self.repositories.products.list(
            self.actor.environment_id,
            self.actor.owner_id,
            status=status,
            after_id=after_id,
            limit=limit + 1,
        )
        next_id = records[limit - 1].product_id if len(records) > limit else None
        return [mappers.to_response(item) for item in records[:limit]], next_id

    async def update(self, product_id: UUID, data: ProductUpdate) -> ProductResponse:
        operation = "product.update"
        request_hash = request_fingerprint(
            operation,
            {
                "product_id": product_id,
                **data.model_dump(exclude={"idempotency_key"}, mode="json"),
            },
        )
        replay = await self._replay(data.idempotency_key, operation, request_hash)
        if replay is not None:
            return replay

        try:
            async with self.repositories.transaction() as repositories:
                now = datetime.now(UTC)
                await repositories.idempotency.insert(
                    pending_record(
                        key=data.idempotency_key,
                        operation=operation,
                        request_hash=request_hash,
                        target_type=_TARGET,
                        target_id=product_id,
                        environment=self.actor.environment_id,
                        owner=self.actor.owner_id,
                        actor=self.actor.actor_id,
                        now=now,
                    ),
                    self.actor.actor_id,
                )
                current = await repositories.products.get_writable_for_update(
                    product_id,
                    self.actor.environment_id,
                    self.actor.owner_id,
                )
                if current is None:
                    raise NotFoundError("Product not found in writable scope")
                if current.version != data.expected_version:
                    raise ConflictError("Product version conflict")
                changes = data.model_dump(
                    exclude_unset=True,
                    exclude={"idempotency_key", "expected_version"},
                )
                changes.update(
                    {
                        "last_idempotency_key": data.idempotency_key,
                        "version": current.version + 1,
                        "updated_at": now,
                        "updated_by": self.actor.actor_id,
                    }
                )
                result = await repositories.products.update_scoped(
                    product_id,
                    self.actor.environment_id,
                    self.actor.owner_id,
                    data.expected_version,
                    changes,
                    self.actor.actor_id,
                )
                if result.rowcount != 1:
                    raise ConflictError("Product changed concurrently")
                updated = await repositories.products.get(
                    product_id,
                    self.actor.environment_id,
                    self.actor.owner_id,
                )
                if updated is None:
                    raise RuntimeError("Updated product was not observable")
                response = mappers.to_response(updated)
                completed = await repositories.idempotency.complete(
                    key=data.idempotency_key,
                    environment=self.actor.environment_id,
                    owner=self.actor.owner_id,
                    operation=operation,
                    request_hash=request_hash,
                    response_body=response.model_dump(mode="json"),
                    updated_at=datetime.now(UTC),
                    actor=self.actor.actor_id,
                )
                if completed.rowcount != 1:
                    raise RuntimeError("Idempotency ledger completion was not observable")
                return response
        except UniqueViolationError as exc:
            replay = await self._replay(data.idempotency_key, operation, request_hash)
            if replay is not None:
                return replay
            raise ConflictError("Product conflicts with an existing record") from exc

    async def delete(
        self,
        product_id: UUID,
        *,
        expected_version: int,
        idempotency_key: str,
    ) -> None:
        operation = "product.delete"
        request_hash = request_fingerprint(
            operation,
            {"product_id": product_id, "expected_version": expected_version},
        )
        replay = await self.repositories.idempotency.get(
            idempotency_key,
            self.actor.environment_id,
            self.actor.owner_id,
        )
        if replay is not None:
            assert_same_request(
                replay,
                operation=operation,
                request_hash=request_hash,
                target_type=_TARGET,
            )
            return

        try:
            async with self.repositories.transaction() as repositories:
                now = datetime.now(UTC)
                await repositories.idempotency.insert(
                    pending_record(
                        key=idempotency_key,
                        operation=operation,
                        request_hash=request_hash,
                        target_type=_TARGET,
                        target_id=product_id,
                        environment=self.actor.environment_id,
                        owner=self.actor.owner_id,
                        actor=self.actor.actor_id,
                        now=now,
                    ),
                    self.actor.actor_id,
                )
                current = await repositories.products.get_any_for_update(
                    product_id,
                    self.actor.environment_id,
                    self.actor.owner_id,
                )
                if current is None or current.is_deleted:
                    raise NotFoundError("Product not found")
                if current.version != expected_version:
                    raise ConflictError("Product version conflict")
                if await repositories.projects.count_for_product(
                    product_id,
                    self.actor.environment_id,
                    self.actor.owner_id,
                ):
                    raise ConflictError("Product still has active projects")
                result = await repositories.products.mark_deleted(
                    product_id,
                    self.actor.environment_id,
                    self.actor.owner_id,
                    expected_version,
                    {
                        "status": "retired",
                        "is_deleted": True,
                        "excluded": 1,
                        "deleted_at": now,
                        "deleted_by": self.actor.actor_id,
                        "updated_at": now,
                        "updated_by": self.actor.actor_id,
                        "version": current.version + 1,
                        "last_idempotency_key": idempotency_key,
                    },
                    self.actor.actor_id,
                )
                if result.rowcount != 1:
                    raise ConflictError("Product changed concurrently")
                completed = await repositories.idempotency.complete(
                    key=idempotency_key,
                    environment=self.actor.environment_id,
                    owner=self.actor.owner_id,
                    operation=operation,
                    request_hash=request_hash,
                    response_body={},
                    updated_at=datetime.now(UTC),
                    actor=self.actor.actor_id,
                )
                if completed.rowcount != 1:
                    raise RuntimeError("Idempotency ledger completion was not observable")
        except UniqueViolationError as exc:
            replay = await self.repositories.idempotency.get(
                idempotency_key,
                self.actor.environment_id,
                self.actor.owner_id,
            )
            if replay is not None:
                assert_same_request(
                    replay,
                    operation=operation,
                    request_hash=request_hash,
                    target_type=_TARGET,
                )
                return
            raise ConflictError("Product conflicts with an existing record") from exc
