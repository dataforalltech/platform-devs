"""Canonical, payload-bound idempotency primitives for portfolio mutations."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel

from app.core.exceptions import ConflictError
from app.models import IdempotencyRecord


def request_fingerprint(operation: str, payload: Any) -> str:
    """Hash a validated request using deterministic JSON encoding."""
    document = {"operation": operation, "request": jsonable_encoder(payload)}
    canonical = json.dumps(
        document,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def pending_record(
    *,
    key: str,
    operation: str,
    request_hash: str,
    target_type: str,
    target_id: UUID,
    environment: int,
    owner: int,
    actor: int,
    now: datetime,
) -> dict[str, Any]:
    return {
        "idempotency_key": key,
        "operation": operation,
        "request_hash": request_hash,
        "target_type": target_type,
        "target_id": target_id,
        "response_body": {},
        "status": "pending",
        "id_environment": environment,
        "id_owner": owner,
        "is_active": True,
        "is_deleted": False,
        "created_at": now,
        "updated_at": now,
        "created_by": actor,
        "updated_by": actor,
    }


def assert_same_request(
    record: IdempotencyRecord,
    *,
    operation: str,
    request_hash: str,
    target_type: str,
) -> None:
    if (
        record.operation != operation
        or record.request_hash != request_hash
        or record.target_type != target_type
    ):
        raise ConflictError("Idempotency key was already used for a different request")
    if record.status != "completed":
        raise ConflictError("Idempotent request is still in progress")


def replay_response[ResponseT: BaseModel](
    record: IdempotencyRecord,
    *,
    operation: str,
    request_hash: str,
    target_type: str,
    response_model: type[ResponseT],
) -> ResponseT:
    assert_same_request(
        record,
        operation=operation,
        request_hash=request_hash,
        target_type=target_type,
    )
    return response_model.model_validate(record.response_body)
