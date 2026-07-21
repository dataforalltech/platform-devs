"""Repository-binding persistence through the canonical ORM."""

from __future__ import annotations

from typing import Any, cast
from uuid import UUID

from platform_core.request_context import get_table_case
from platform_database.orm import Condition, Operator, Pagination, Repository, SelectQuery, Sort
from platform_database.orm.results import QueryResult

from app.models import RepositoryBindingRecord
from app.modules.scope import combine, visible, writable


class RepositoryBindingRepository:
    def __init__(self, repository: Repository[RepositoryBindingRecord]) -> None:
        self._repo = repository

    async def get(
        self, binding_id: UUID, environment: int, owner: int
    ) -> RepositoryBindingRecord | None:
        return await self._repo.find_one(
            combine(
                visible(environment, owner),
                Condition(column="binding_id", op=Operator.EQ, value=binding_id),
            )
        )

    async def get_any(
        self, binding_id: UUID, environment: int, owner: int
    ) -> RepositoryBindingRecord | None:
        result = await self._repo.find(
            where=combine(
                Condition(column="id_environment", op=Operator.EQ, value=environment),
                Condition(column="id_owner", op=Operator.EQ, value=owner),
                Condition(column="binding_id", op=Operator.EQ, value=binding_id),
            ),
            include_soft_deleted=True,
            limit=1,
        )
        return result.first()

    async def get_any_for_update(
        self, binding_id: UUID, environment: int, owner: int
    ) -> RepositoryBindingRecord | None:
        table = (
            "PORTFOLIO_PROJECT_REPOSITORY_BINDINGS"
            if get_table_case() == "upper"
            else "portfolio_project_repository_bindings"
        )
        result = await self._repo.execute_query_object(
            SelectQuery(
                table=table,
                where=combine(
                    Condition(column="id_environment", op=Operator.EQ, value=environment),
                    Condition(column="id_owner", op=Operator.EQ, value=owner),
                    Condition(column="binding_id", op=Operator.EQ, value=binding_id),
                ),
                pagination=Pagination(limit=1),
                for_update=True,
                include_soft_deleted=True,
            ),
            into=RepositoryBindingRecord,
        )
        return cast(QueryResult[RepositoryBindingRecord], result).first()

    async def by_idempotency(
        self, key: str, environment: int, owner: int
    ) -> RepositoryBindingRecord | None:
        result = await self._repo.find(
            where=combine(
                Condition(column="id_environment", op=Operator.EQ, value=environment),
                Condition(column="id_owner", op=Operator.EQ, value=owner),
                Condition(column="last_idempotency_key", op=Operator.EQ, value=key),
            ),
            include_soft_deleted=True,
            limit=1,
        )
        return result.first()

    async def list_for_project(
        self,
        project_id: UUID,
        environment: int,
        owner: int,
        *,
        provider: str | None,
        role: str | None,
    ) -> list[RepositoryBindingRecord]:
        filters: list[Any] = [
            visible(environment, owner),
            Condition(column="project_id", op=Operator.EQ, value=project_id),
        ]
        if provider:
            filters.append(Condition(column="provider", op=Operator.EQ, value=provider))
        if role:
            filters.append(Condition(column="role", op=Operator.EQ, value=role))
        result = await self._repo.find(
            where=combine(*filters),
            order_by=[Sort(column="binding_id")],
            limit=100,
        )
        return result.models()

    async def count_for_project(self, project_id: UUID, environment: int, owner: int) -> int:
        return await self._repo.count(
            where=combine(
                writable(environment, owner),
                Condition(column="project_id", op=Operator.EQ, value=project_id),
            )
        )

    async def insert(self, data: dict[str, Any], actor: int):
        return await self._repo.insert(data, user_id=actor, returning=None)

    async def detach(
        self,
        project_id: UUID,
        binding_id: UUID,
        environment: int,
        owner: int,
        expected_version: int,
        data: dict[str, Any],
        actor: int,
    ):
        return await self._repo.update_where(
            combine(
                writable(environment, owner),
                Condition(column="project_id", op=Operator.EQ, value=project_id),
                Condition(column="binding_id", op=Operator.EQ, value=binding_id),
                Condition(column="version", op=Operator.EQ, value=expected_version),
            ),
            data,
            user_id=actor,
        )
