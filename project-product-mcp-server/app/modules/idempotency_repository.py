"""Tenant-local idempotency ledger persistence."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from platform_database.orm import Condition, Operator, Repository

from app.models import IdempotencyRecord
from app.modules.scope import combine


class IdempotencyRepository:
    def __init__(self, repository: Repository[IdempotencyRecord]) -> None:
        self._repo = repository

    async def get(
        self,
        key: str,
        environment: int,
        owner: int,
    ) -> IdempotencyRecord | None:
        return await self._repo.find_one(
            combine(
                Condition(column="id_environment", op=Operator.EQ, value=environment),
                Condition(column="id_owner", op=Operator.EQ, value=owner),
                Condition(column="idempotency_key", op=Operator.EQ, value=key),
            )
        )

    async def insert(self, data: dict[str, Any], actor: int):
        return await self._repo.insert(data, user_id=actor, returning=None)

    async def complete(
        self,
        *,
        key: str,
        environment: int,
        owner: int,
        operation: str,
        request_hash: str,
        response_body: dict[str, Any],
        updated_at: datetime,
        actor: int,
    ):
        return await self._repo.update_where(
            combine(
                Condition(column="id_environment", op=Operator.EQ, value=environment),
                Condition(column="id_owner", op=Operator.EQ, value=owner),
                Condition(column="idempotency_key", op=Operator.EQ, value=key),
                Condition(column="operation", op=Operator.EQ, value=operation),
                Condition(column="request_hash", op=Operator.EQ, value=request_hash),
                Condition(column="status", op=Operator.EQ, value="pending"),
            ),
            {
                "status": "completed",
                "response_body": response_body,
                "updated_at": updated_at,
                "updated_by": actor,
            },
            user_id=actor,
        )
