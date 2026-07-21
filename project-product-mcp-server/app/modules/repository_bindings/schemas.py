"""Repository-binding HTTP contracts."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from platform_project_product.schemas import (
    RepositoryBindingCreate,
    RepositoryBindingResponse,
    RepositoryRole,
)


class RepositoryBindingListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[RepositoryBindingResponse]
    next_after_id: UUID | None = None


class DetachRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: str = Field(min_length=8, max_length=128)
    expected_version: int = Field(ge=1)


__all__ = [
    "DetachRequest",
    "RepositoryBindingCreate",
    "RepositoryBindingListResponse",
    "RepositoryBindingResponse",
    "RepositoryRole",
]
