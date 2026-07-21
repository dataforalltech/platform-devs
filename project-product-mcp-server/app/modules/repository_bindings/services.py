"""Provider-neutral repository binding rules with transactional parent locking."""

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
from app.modules.repository_bindings import mappers
from platform_project_product.schemas import RepositoryBindingCreate, RepositoryBindingResponse

_TARGET = "repository_binding"


class RepositoryBindingService(BaseService[dict, str]):
    def __init__(self, repositories: PortfolioRepositories, actor: ActorContext) -> None:
        super().__init__(id_user_ops=actor.actor_id, request_id=actor.request_id)
        self.repositories = repositories
        self.actor = actor

    async def _replay(
        self,
        key: str,
        operation: str,
        request_hash: str,
    ) -> RepositoryBindingResponse | None:
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
            response_model=RepositoryBindingResponse,
        )

    async def attach(
        self,
        project_id: UUID,
        data: RepositoryBindingCreate,
    ) -> RepositoryBindingResponse:
        operation = "repository_binding.attach"
        request_hash = request_fingerprint(
            operation,
            {
                "project_id": project_id,
                **data.model_dump(exclude={"idempotency_key"}, mode="json"),
            },
        )
        replay = await self._replay(data.idempotency_key, operation, request_hash)
        if replay is not None:
            return replay

        binding_id = uuid4()
        try:
            async with self.repositories.transaction() as repositories:
                now = datetime.now(UTC)
                await repositories.idempotency.insert(
                    pending_record(
                        key=data.idempotency_key,
                        operation=operation,
                        request_hash=request_hash,
                        target_type=_TARGET,
                        target_id=binding_id,
                        environment=self.actor.environment_id,
                        owner=self.actor.owner_id,
                        actor=self.actor.actor_id,
                        now=now,
                    ),
                    self.actor.actor_id,
                )
                project = await repositories.projects.get_writable_for_update(
                    project_id,
                    self.actor.environment_id,
                    self.actor.owner_id,
                )
                if project is None:
                    raise NotFoundError("Project not found in tenant scope")
                payload = {
                    **data.model_dump(exclude={"idempotency_key"}, mode="json"),
                    "binding_id": binding_id,
                    "project_id": project_id,
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
                await repositories.bindings.insert(payload, self.actor.actor_id)
                created = await repositories.bindings.get(
                    binding_id,
                    self.actor.environment_id,
                    self.actor.owner_id,
                )
                if created is None:
                    raise RuntimeError("Created repository binding was not observable")
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
            raise ConflictError("Repository binding conflicts with an existing record") from exc

    async def list(
        self,
        project_id: UUID,
        *,
        provider: str | None,
        role: str | None,
    ) -> list[RepositoryBindingResponse]:
        project = await self.repositories.projects.get(
            project_id,
            self.actor.environment_id,
            self.actor.owner_id,
        )
        if project is None:
            raise NotFoundError("Project not found")
        rows = await self.repositories.bindings.list_for_project(
            project_id,
            self.actor.environment_id,
            self.actor.owner_id,
            provider=provider,
            role=role,
        )
        return [mappers.to_response(item) for item in rows]

    async def detach(
        self,
        project_id: UUID,
        binding_id: UUID,
        *,
        expected_version: int,
        idempotency_key: str,
    ) -> None:
        operation = "repository_binding.detach"
        request_hash = request_fingerprint(
            operation,
            {
                "project_id": project_id,
                "binding_id": binding_id,
                "expected_version": expected_version,
            },
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
                        target_id=binding_id,
                        environment=self.actor.environment_id,
                        owner=self.actor.owner_id,
                        actor=self.actor.actor_id,
                        now=now,
                    ),
                    self.actor.actor_id,
                )
                current = await repositories.bindings.get_any_for_update(
                    binding_id,
                    self.actor.environment_id,
                    self.actor.owner_id,
                )
                if current is None or current.is_deleted or current.project_id != project_id:
                    raise NotFoundError("Repository binding not found")
                if current.version != expected_version:
                    raise ConflictError("Repository binding version conflict")
                result = await repositories.bindings.detach(
                    project_id,
                    binding_id,
                    self.actor.environment_id,
                    self.actor.owner_id,
                    expected_version,
                    {
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
                    raise ConflictError("Repository binding changed concurrently")
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
            raise ConflictError("Repository binding conflicts with an existing record") from exc

    async def detach_by_id(
        self,
        binding_id: UUID,
        *,
        expected_version: int,
        idempotency_key: str,
    ) -> None:
        current = await self.repositories.bindings.get_any(
            binding_id,
            self.actor.environment_id,
            self.actor.owner_id,
        )
        if current is None:
            raise NotFoundError("Repository binding not found")
        await self.detach(
            current.project_id,
            binding_id,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
        )
