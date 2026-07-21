"""Product HTTP contracts."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from platform_project_product.schemas import ProductCreate, ProductResponse, ProductUpdate


class ProductListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[ProductResponse]
    next_after_id: UUID | None = None


class DeleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: str = Field(min_length=8, max_length=128)
    expected_version: int = Field(ge=1)


__all__ = [
    "DeleteRequest",
    "ProductCreate",
    "ProductListResponse",
    "ProductResponse",
    "ProductUpdate",
]
