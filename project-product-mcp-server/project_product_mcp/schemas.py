"""JSON Schemas shared by runtime definitions and canonical contracts."""

from __future__ import annotations

from typing import Any

UUID_SCHEMA = {"type": "string", "format": "uuid", "minLength": 36, "maxLength": 36}
OPAQUE_REF_SCHEMA = {"type": "string", "minLength": 1, "maxLength": 512}
NULLABLE_OPAQUE_REF_SCHEMA = {"anyOf": [OPAQUE_REF_SCHEMA, {"type": "null"}]}
IDEMPOTENCY_SCHEMA = {
    "type": "string",
    "minLength": 8,
    "maxLength": 128,
    "pattern": "^[A-Za-z0-9._:-]+$",
}
SLUG_SCHEMA = {
    "type": "string",
    "minLength": 1,
    "maxLength": 80,
    "pattern": "^[a-z0-9]+(?:-[a-z0-9]+)*$",
}
OWNER_REFS_SCHEMA = {
    "type": "array",
    "maxItems": 100,
    "uniqueItems": True,
    "items": OPAQUE_REF_SCHEMA,
}
SERVICE_REFS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "governance_ref": NULLABLE_OPAQUE_REF_SCHEMA,
        "schedule_ref": NULLABLE_OPAQUE_REF_SCHEMA,
        "communication_ref": NULLABLE_OPAQUE_REF_SCHEMA,
        "notification_ref": NULLABLE_OPAQUE_REF_SCHEMA,
    },
}

_PRODUCT_STATUS = ["planned", "active", "paused", "retired"]
_PROJECT_STATUS = ["planned", "active", "paused", "completed", "archived"]

PRODUCT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "product_id": UUID_SCHEMA,
        "slug": SLUG_SCHEMA,
        "name": {"type": "string", "minLength": 1, "maxLength": 200},
        "description": {"anyOf": [{"type": "string", "maxLength": 4000}, {"type": "null"}]},
        "status": {"type": "string", "enum": _PRODUCT_STATUS},
        "owner_user_refs": OWNER_REFS_SCHEMA,
        "version": {"type": "integer", "minimum": 1},
        "created_at": {"type": "string", "format": "date-time"},
        "updated_at": {"type": "string", "format": "date-time"},
        "created_by_ref": OPAQUE_REF_SCHEMA,
        "updated_by_ref": OPAQUE_REF_SCHEMA,
    },
    "required": [
        "product_id",
        "slug",
        "name",
        "description",
        "status",
        "owner_user_refs",
        "version",
        "created_at",
        "updated_at",
        "created_by_ref",
        "updated_by_ref",
    ],
}

PROJECT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "project_id": UUID_SCHEMA,
        "product_id": UUID_SCHEMA,
        "slug": SLUG_SCHEMA,
        "name": {"type": "string", "minLength": 1, "maxLength": 200},
        "description": {"anyOf": [{"type": "string", "maxLength": 4000}, {"type": "null"}]},
        "status": {"type": "string", "enum": _PROJECT_STATUS},
        "owner_user_refs": OWNER_REFS_SCHEMA,
        "service_refs": SERVICE_REFS_SCHEMA,
        "version": {"type": "integer", "minimum": 1},
        "created_at": {"type": "string", "format": "date-time"},
        "updated_at": {"type": "string", "format": "date-time"},
        "created_by_ref": OPAQUE_REF_SCHEMA,
        "updated_by_ref": OPAQUE_REF_SCHEMA,
    },
    "required": [
        "project_id",
        "product_id",
        "slug",
        "name",
        "description",
        "status",
        "owner_user_refs",
        "service_refs",
        "version",
        "created_at",
        "updated_at",
        "created_by_ref",
        "updated_by_ref",
    ],
}

REPOSITORY_METADATA_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "display_name": {
            "anyOf": [
                {"type": "string", "minLength": 1, "maxLength": 200},
                {"type": "null"},
            ]
        },
        "default_branch": {
            "anyOf": [
                {"type": "string", "minLength": 1, "maxLength": 255},
                {"type": "null"},
            ]
        },
        "web_url": {
            "anyOf": [
                {
                    "type": "string",
                    "format": "uri",
                    "pattern": r"^https?://(?![^/?#]*@)(?!.*[\\#\s])[^/?#]+(?:[/?][^#\\\s]*)?$",
                    "maxLength": 2048,
                },
                {"type": "null"},
            ]
        },
    },
}

REPOSITORY_BINDING_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "binding_id": UUID_SCHEMA,
        "project_id": UUID_SCHEMA,
        "provider": {
            "type": "string",
            "minLength": 1,
            "maxLength": 64,
            "pattern": "^[a-z0-9][a-z0-9._-]*$",
        },
        "connector_ref": OPAQUE_REF_SCHEMA,
        "repository_ref": OPAQUE_REF_SCHEMA,
        "role": {
            "type": "string",
            "enum": ["source", "documentation", "infrastructure", "deployment", "other"],
        },
        "metadata": REPOSITORY_METADATA_SCHEMA,
        "version": {"type": "integer", "minimum": 1},
        "created_at": {"type": "string", "format": "date-time"},
        "updated_at": {"type": "string", "format": "date-time"},
        "created_by_ref": OPAQUE_REF_SCHEMA,
        "updated_by_ref": OPAQUE_REF_SCHEMA,
    },
    "required": [
        "binding_id",
        "project_id",
        "provider",
        "connector_ref",
        "repository_ref",
        "role",
        "metadata",
        "version",
        "created_at",
        "updated_at",
        "created_by_ref",
        "updated_by_ref",
    ],
}

DELETE_PRODUCT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {"product_id": UUID_SCHEMA, "deleted": {"const": True}},
    "required": ["product_id", "deleted"],
}
DELETE_PROJECT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {"project_id": UUID_SCHEMA, "deleted": {"const": True}},
    "required": ["project_id", "deleted"],
}
DETACH_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {"binding_id": UUID_SCHEMA, "detached": {"const": True}},
    "required": ["binding_id", "detached"],
}

PRODUCT_CREATE_INPUT = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "idempotency_key": IDEMPOTENCY_SCHEMA,
        "slug": SLUG_SCHEMA,
        "name": {"type": "string", "minLength": 1, "maxLength": 200},
        "description": {"anyOf": [{"type": "string", "maxLength": 4000}, {"type": "null"}]},
        "status": {"type": "string", "enum": _PRODUCT_STATUS, "default": "active"},
        "owner_user_refs": OWNER_REFS_SCHEMA,
    },
    "required": ["idempotency_key", "slug", "name"],
}
PRODUCT_GET_INPUT = {
    "type": "object",
    "additionalProperties": False,
    "properties": {"product_id": UUID_SCHEMA},
    "required": ["product_id"],
}
PRODUCT_LIST_INPUT = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "status": {"type": "string", "enum": _PRODUCT_STATUS},
        "after_id": UUID_SCHEMA,
        "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 50},
    },
}
PRODUCT_LIST_OUTPUT = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "items": {"type": "array", "items": PRODUCT_SCHEMA},
        "next_after_id": {"anyOf": [UUID_SCHEMA, {"type": "null"}]},
    },
    "required": ["items", "next_after_id"],
}
PRODUCT_UPDATE_INPUT = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "idempotency_key": IDEMPOTENCY_SCHEMA,
        "product_id": UUID_SCHEMA,
        "expected_version": {"type": "integer", "minimum": 1},
        "changes": {
            "type": "object",
            "additionalProperties": False,
            "minProperties": 1,
            "properties": {
                "slug": SLUG_SCHEMA,
                "name": {"type": "string", "minLength": 1, "maxLength": 200},
                "description": {"anyOf": [{"type": "string", "maxLength": 4000}, {"type": "null"}]},
                "status": {"type": "string", "enum": _PRODUCT_STATUS},
                "owner_user_refs": OWNER_REFS_SCHEMA,
            },
        },
    },
    "required": ["idempotency_key", "product_id", "expected_version", "changes"],
}
PRODUCT_DELETE_INPUT = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "idempotency_key": IDEMPOTENCY_SCHEMA,
        "product_id": UUID_SCHEMA,
        "expected_version": {"type": "integer", "minimum": 1},
    },
    "required": ["idempotency_key", "product_id", "expected_version"],
}

PROJECT_CREATE_INPUT = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "idempotency_key": IDEMPOTENCY_SCHEMA,
        "product_id": UUID_SCHEMA,
        "slug": SLUG_SCHEMA,
        "name": {"type": "string", "minLength": 1, "maxLength": 200},
        "description": {"anyOf": [{"type": "string", "maxLength": 4000}, {"type": "null"}]},
        "status": {"type": "string", "enum": _PROJECT_STATUS, "default": "active"},
        "owner_user_refs": OWNER_REFS_SCHEMA,
        "service_refs": SERVICE_REFS_SCHEMA,
    },
    "required": ["idempotency_key", "product_id", "slug", "name"],
}
PROJECT_GET_INPUT = {
    "type": "object",
    "additionalProperties": False,
    "properties": {"project_id": UUID_SCHEMA},
    "required": ["project_id"],
}
PROJECT_LIST_INPUT = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "product_id": UUID_SCHEMA,
        "status": {"type": "string", "enum": _PROJECT_STATUS},
        "after_id": UUID_SCHEMA,
        "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 50},
    },
}
PROJECT_LIST_OUTPUT = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "items": {"type": "array", "items": PROJECT_SCHEMA},
        "next_after_id": {"anyOf": [UUID_SCHEMA, {"type": "null"}]},
    },
    "required": ["items", "next_after_id"],
}
PROJECT_UPDATE_INPUT = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "idempotency_key": IDEMPOTENCY_SCHEMA,
        "project_id": UUID_SCHEMA,
        "expected_version": {"type": "integer", "minimum": 1},
        "changes": {
            "type": "object",
            "additionalProperties": False,
            "minProperties": 1,
            "properties": {
                "slug": SLUG_SCHEMA,
                "name": {"type": "string", "minLength": 1, "maxLength": 200},
                "description": {"anyOf": [{"type": "string", "maxLength": 4000}, {"type": "null"}]},
                "status": {"type": "string", "enum": _PROJECT_STATUS},
                "owner_user_refs": OWNER_REFS_SCHEMA,
                "service_refs": SERVICE_REFS_SCHEMA,
            },
        },
    },
    "required": ["idempotency_key", "project_id", "expected_version", "changes"],
}
PROJECT_DELETE_INPUT = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "idempotency_key": IDEMPOTENCY_SCHEMA,
        "project_id": UUID_SCHEMA,
        "expected_version": {"type": "integer", "minimum": 1},
    },
    "required": ["idempotency_key", "project_id", "expected_version"],
}

REPOSITORY_ATTACH_INPUT = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "idempotency_key": IDEMPOTENCY_SCHEMA,
        "project_id": UUID_SCHEMA,
        "provider": {
            "type": "string",
            "minLength": 1,
            "maxLength": 64,
            "pattern": "^[a-z0-9][a-z0-9._-]*$",
        },
        "connector_ref": OPAQUE_REF_SCHEMA,
        "repository_ref": OPAQUE_REF_SCHEMA,
        "role": {
            "type": "string",
            "enum": ["source", "documentation", "infrastructure", "deployment", "other"],
            "default": "source",
        },
        "metadata": REPOSITORY_METADATA_SCHEMA,
    },
    "required": ["idempotency_key", "project_id", "provider", "connector_ref", "repository_ref"],
}
REPOSITORY_LIST_INPUT = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "project_id": UUID_SCHEMA,
        "provider": {
            "type": "string",
            "minLength": 1,
            "maxLength": 64,
            "pattern": "^[a-z0-9][a-z0-9._-]*$",
        },
        "role": {
            "type": "string",
            "enum": ["source", "documentation", "infrastructure", "deployment", "other"],
        },
    },
    "required": ["project_id"],
}
REPOSITORY_LIST_OUTPUT = {
    "type": "object",
    "additionalProperties": False,
    "properties": {"items": {"type": "array", "items": REPOSITORY_BINDING_SCHEMA}},
    "required": ["items"],
}
REPOSITORY_DETACH_INPUT = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "idempotency_key": IDEMPOTENCY_SCHEMA,
        "binding_id": UUID_SCHEMA,
        "expected_version": {"type": "integer", "minimum": 1},
    },
    "required": ["idempotency_key", "binding_id", "expected_version"],
}
