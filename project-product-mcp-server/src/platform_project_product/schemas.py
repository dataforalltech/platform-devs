"""Public Pydantic contracts shared by the REST API and typed clients."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, overload
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

ProductStatus = Literal["planned", "active", "paused", "retired"]
ProjectStatus = Literal["planned", "active", "paused", "completed", "archived"]
RepositoryRole = Literal["source", "documentation", "infrastructure", "deployment", "other"]


@overload
def _validate_owner_refs(value: list[str]) -> list[str]: ...


@overload
def _validate_owner_refs(value: None) -> None: ...


def _validate_owner_refs(value: list[str] | None) -> list[str] | None:
    if value is None:
        return None
    if any(not item or len(item) > 512 for item in value):
        raise ValueError("owner references must be non-empty and at most 512 characters")
    if len(set(value)) != len(value):
        raise ValueError("owner references must be unique")
    return value


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AuditResponse(StrictModel):
    version: int = Field(ge=1)
    is_active: bool
    id_environment: int = Field(ge=0, le=32767)
    id_owner: int = Field(ge=0)
    created_at: datetime
    updated_at: datetime
    created_by: int = Field(ge=1)
    updated_by: int = Field(ge=1)


class ProductCreate(StrictModel):
    idempotency_key: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")
    slug: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    status: ProductStatus = "active"
    owner_user_refs: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("owner_user_refs")
    @classmethod
    def unique_owner_refs(cls, value: list[str]) -> list[str]:
        return _validate_owner_refs(value)


class ProductUpdate(StrictModel):
    idempotency_key: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")
    expected_version: int = Field(ge=1)
    slug: str | None = Field(
        default=None, min_length=1, max_length=80, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
    )
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    status: ProductStatus | None = None
    owner_user_refs: list[str] | None = Field(default=None, max_length=100)

    @field_validator("owner_user_refs")
    @classmethod
    def valid_owner_refs(cls, value: list[str] | None) -> list[str] | None:
        return _validate_owner_refs(value)


class ProductResponse(AuditResponse):
    product_id: UUID
    slug: str
    name: str
    description: str | None
    status: ProductStatus
    owner_user_refs: list[str]


class ServiceReferences(StrictModel):
    governance_ref: str | None = Field(default=None, max_length=512)
    schedule_ref: str | None = Field(default=None, max_length=512)
    communication_ref: str | None = Field(default=None, max_length=512)
    notification_ref: str | None = Field(default=None, max_length=512)

    @field_validator(
        "governance_ref", "schedule_ref", "communication_ref", "notification_ref"
    )
    @classmethod
    def _blank_ref_is_absent(cls, value: str | None) -> str | None:
        # An opaque reference is either present or absent; an empty/blank string is
        # neither and would violate the MCP output contract (minLength 1 or null),
        # making the record unreadable through the MCP surface.
        if value is None:
            return None
        return value.strip() or None


class ProjectCreate(StrictModel):
    idempotency_key: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")
    product_id: UUID
    slug: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    status: ProjectStatus = "active"
    owner_user_refs: list[str] = Field(default_factory=list, max_length=100)
    service_refs: ServiceReferences = Field(default_factory=ServiceReferences)

    @field_validator("owner_user_refs")
    @classmethod
    def valid_owner_refs(cls, value: list[str]) -> list[str]:
        return _validate_owner_refs(value)


class ProjectUpdate(StrictModel):
    idempotency_key: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")
    expected_version: int = Field(ge=1)
    slug: str | None = Field(
        default=None, min_length=1, max_length=80, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
    )
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    status: ProjectStatus | None = None
    owner_user_refs: list[str] | None = Field(default=None, max_length=100)
    service_refs: ServiceReferences | None = None

    @field_validator("owner_user_refs")
    @classmethod
    def valid_owner_refs(cls, value: list[str] | None) -> list[str] | None:
        return _validate_owner_refs(value)


class ProjectResponse(AuditResponse):
    project_id: UUID
    product_id: UUID
    slug: str
    name: str
    description: str | None
    status: ProjectStatus
    owner_user_refs: list[str]
    service_refs: ServiceReferences


class RepositoryMetadata(StrictModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    default_branch: str | None = Field(default=None, min_length=1, max_length=255)
    web_url: str | None = Field(default=None, max_length=2048)

    @field_validator("web_url")
    @classmethod
    def validate_web_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            parsed = urlsplit(value)
            hostname = parsed.hostname
            port = parsed.port
        except ValueError as exc:
            raise ValueError("web_url must be a valid HTTP(S) URL") from exc
        if (
            parsed.scheme not in {"http", "https"}
            or hostname is None
            or parsed.username is not None
            or parsed.password is not None
            or bool(parsed.fragment)
            or "\\" in value
            or "#" in value
            or port == 0
            or any(ch.isspace() or ord(ch) < 32 for ch in value)
        ):
            raise ValueError(
                "web_url must use HTTP(S), include a host, and omit credentials, "
                "fragments, and whitespace"
            )
        return value


class RepositoryBindingCreate(StrictModel):
    idempotency_key: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")
    provider: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    connector_ref: str = Field(min_length=1, max_length=512)
    repository_ref: str = Field(min_length=1, max_length=512)
    role: RepositoryRole = "source"
    metadata: RepositoryMetadata = Field(default_factory=RepositoryMetadata)


class RepositoryBindingResponse(AuditResponse):
    binding_id: UUID
    project_id: UUID
    provider: str
    connector_ref: str
    repository_ref: str
    role: RepositoryRole
    metadata: RepositoryMetadata


class Page(StrictModel):
    items: list[Any]
    next_after_id: UUID | None = None
