"""Product persistence through the canonical engine-agnostic ORM."""

from __future__ import annotations

from typing import Any, cast
from uuid import UUID

from platform_core.request_context import get_table_case
from platform_database.orm import Condition, Operator, Pagination, Repository, SelectQuery, Sort
from platform_database.orm.results import QueryResult

from app.models import ProductRecord
from app.modules.scope import combine, visible, writable


class ProductRepository:
    def __init__(self, repository: Repository[ProductRecord]) -> None:
        self._repo = repository

    async def get(self, product_id: UUID, environment: int, owner: int) -> ProductRecord | None:
        return await self._repo.find_one(
            combine(
                visible(environment, owner),
                Condition(column="product_id", op=Operator.EQ, value=product_id),
            )
        )

    async def get_writable(
        self, product_id: UUID, environment: int, owner: int
    ) -> ProductRecord | None:
        return await self._repo.find_one(
            combine(
                writable(environment, owner),
                Condition(column="product_id", op=Operator.EQ, value=product_id),
            )
        )

    async def get_writable_for_update(
        self, product_id: UUID, environment: int, owner: int
    ) -> ProductRecord | None:
        table = "PORTFOLIO_PRODUCTS" if get_table_case() == "upper" else "portfolio_products"
        result = await self._repo.execute_query_object(
            SelectQuery(
                table=table,
                where=combine(
                    writable(environment, owner),
                    Condition(column="product_id", op=Operator.EQ, value=product_id),
                ),
                pagination=Pagination(limit=1),
                for_update=True,
            ),
            into=ProductRecord,
        )
        return cast(QueryResult[ProductRecord], result).first()

    async def get_any(self, product_id: UUID, environment: int, owner: int) -> ProductRecord | None:
        result = await self._repo.find(
            where=combine(
                Condition(column="id_environment", op=Operator.EQ, value=environment),
                Condition(column="id_owner", op=Operator.EQ, value=owner),
                Condition(column="product_id", op=Operator.EQ, value=product_id),
            ),
            include_soft_deleted=True,
            limit=1,
        )
        return result.first()

    async def get_any_for_update(
        self, product_id: UUID, environment: int, owner: int
    ) -> ProductRecord | None:
        table = "PORTFOLIO_PRODUCTS" if get_table_case() == "upper" else "portfolio_products"
        result = await self._repo.execute_query_object(
            SelectQuery(
                table=table,
                where=combine(
                    Condition(column="id_environment", op=Operator.EQ, value=environment),
                    Condition(column="id_owner", op=Operator.EQ, value=owner),
                    Condition(column="product_id", op=Operator.EQ, value=product_id),
                ),
                pagination=Pagination(limit=1),
                for_update=True,
                include_soft_deleted=True,
            ),
            into=ProductRecord,
        )
        return cast(QueryResult[ProductRecord], result).first()

    async def by_idempotency(self, key: str, environment: int, owner: int) -> ProductRecord | None:
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

    async def by_slug(self, slug: str, environment: int, owner: int) -> ProductRecord | None:
        return await self._repo.find_one(
            combine(
                writable(environment, owner),
                Condition(column="slug", op=Operator.EQ, value=slug),
            )
        )

    async def list(
        self,
        environment: int,
        owner: int,
        *,
        status: str | None,
        after_id: UUID | None,
        limit: int,
    ) -> list[ProductRecord]:
        filters: list[Any] = [visible(environment, owner)]
        if status:
            filters.append(Condition(column="status", op=Operator.EQ, value=status))
        if after_id:
            filters.append(Condition(column="product_id", op=Operator.GT, value=after_id))
        result = await self._repo.find(
            where=combine(*filters),
            order_by=[Sort(column="product_id")],
            limit=limit,
        )
        return result.models()

    async def insert(self, data: dict[str, Any], actor: int):
        return await self._repo.insert(data, user_id=actor, returning=None)

    async def update_scoped(
        self,
        product_id: UUID,
        environment: int,
        owner: int,
        expected_version: int,
        data: dict[str, Any],
        actor: int,
    ):
        return await self._repo.update_where(
            combine(
                writable(environment, owner),
                Condition(column="product_id", op=Operator.EQ, value=product_id),
                Condition(column="version", op=Operator.EQ, value=expected_version),
            ),
            data,
            user_id=actor,
        )

    async def mark_deleted(
        self,
        product_id: UUID,
        environment: int,
        owner: int,
        expected_version: int,
        data: dict[str, Any],
        actor: int,
    ):
        return await self.update_scoped(
            product_id, environment, owner, expected_version, data, actor
        )
