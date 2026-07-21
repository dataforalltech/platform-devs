"""Pydantic entity models consumed by ``platform_database.orm``."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _decode_driver_json(value: Any) -> Any:
    """Decode JSON/JSONB text returned by aiomysql and asyncpg."""
    if not isinstance(value, (str, bytes, bytearray)):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError) as exc:
        raise ValueError("Database returned malformed JSON") from exc


class Record(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    version: int = Field(default=1, ge=1)
    last_idempotency_key: str = Field(min_length=8, max_length=128)
    is_active: bool = True
    is_deleted: bool = False
    id_environment: int = Field(ge=0, le=32767)
    id_owner: int = Field(ge=0)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    deleted_at: datetime | None = None
    created_by: int | None = None
    updated_by: int | None = None
    deleted_by: int | None = None


class ProductRecord(Record):
    product_id: UUID
    slug: str
    name: str
    description: str | None = None
    status: str
    owner_user_refs: list[str] = Field(default_factory=list)

    @field_validator("owner_user_refs", mode="before")
    @classmethod
    def decode_owner_user_refs(cls, value: Any) -> Any:
        return _decode_driver_json(value)


class ProjectRecord(Record):
    project_id: UUID
    product_id: UUID
    slug: str
    name: str
    description: str | None = None
    status: str
    owner_user_refs: list[str] = Field(default_factory=list)
    service_refs: dict[str, str | None] = Field(default_factory=dict)

    @field_validator("owner_user_refs", "service_refs", mode="before")
    @classmethod
    def decode_json_fields(cls, value: Any) -> Any:
        return _decode_driver_json(value)


class RepositoryBindingRecord(Record):
    binding_id: UUID
    project_id: UUID
    provider: str
    connector_ref: str
    repository_ref: str
    role: str
    metadata: dict[str, str | None] = Field(default_factory=dict)
    external_link: dict[str, Any] | None = None

    @field_validator("metadata", "external_link", mode="before")
    @classmethod
    def decode_metadata(cls, value: Any) -> Any:
        return _decode_driver_json(value)


class IdempotencyRecord(BaseModel):
    """Immutable request identity plus the committed response snapshot."""

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    id_environment: int = Field(ge=0, le=32767)
    id_owner: int = Field(ge=0)
    idempotency_key: str = Field(min_length=8, max_length=128)
    operation: str = Field(min_length=1, max_length=64)
    request_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_type: str = Field(min_length=1, max_length=32)
    target_id: UUID
    response_body: dict[str, Any] = Field(default_factory=dict)
    status: Literal["pending", "completed"] = "pending"
    is_active: bool = True
    is_deleted: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None
    created_by: int | None = None
    updated_by: int | None = None

    @field_validator("response_body", mode="before")
    @classmethod
    def decode_response_body(cls, value: Any) -> Any:
        return _decode_driver_json(value)
