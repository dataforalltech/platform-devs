"""Project HTTP contracts."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from platform_project_product.schemas import ProjectCreate, ProjectResponse, ProjectUpdate


class ProjectListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[ProjectResponse]
    next_after_id: UUID | None = None


class DeleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: str = Field(min_length=8, max_length=128)
    expected_version: int = Field(ge=1)


__all__ = [
    "DeleteRequest",
    "ProjectCreate",
    "ProjectListResponse",
    "ProjectResponse",
    "ProjectUpdate",
]
