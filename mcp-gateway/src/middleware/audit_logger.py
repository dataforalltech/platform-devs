"""Append-only, hash-chained and redacted activity ledger."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from typing import Any

import psycopg2

_SENSITIVE = {
    "authorization",
    "password",
    "secret",
    "token",
    "access_token",
    "refresh_token",
    "private_key",
    "private_key_pem",
    "credential",
    "value",
}
_MAX_STRING = 2048
class AuditUnavailable(RuntimeError):
    pass


def _sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    compact = normalized.replace("_", "")
    return normalized in _SENSITIVE or any(
        marker in compact
        for marker in (
            "authorization",
            "password",
            "clientsecret",
            "apikey",
            "privatekey",
            "accesstoken",
            "refreshtoken",
            "credential",
        )
    )


def redact(value: Any, *, key: str | None = None, depth: int = 0) -> Any:
    if key and _sensitive_key(key):
        return "<redacted>"
    if depth >= 8:
        return "<max-depth>"
    if isinstance(value, dict):
        return {str(k): redact(v, key=str(k), depth=depth + 1) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(item, depth=depth + 1) for item in value[:100]]
    if isinstance(value, str) and len(value) > _MAX_STRING:
        return f"{value[:_MAX_STRING]}<truncated>"
    return value


def _connection():
    required = ("PG_HOST", "PG_PORT", "PG_DB", "PG_USER", "PG_PASSWORD")
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        raise AuditUnavailable(f"audit database configuration missing: {', '.join(missing)}")
    try:
        return psycopg2.connect(
            host=os.environ["PG_HOST"],
            port=int(os.environ["PG_PORT"]),
            database=os.environ["PG_DB"],
            user=os.environ["PG_USER"],
            password=os.environ["PG_PASSWORD"],
            connect_timeout=5,
        )
    except psycopg2.Error as exc:
        raise AuditUnavailable("activity ledger unavailable") from exc


def _assert_sync() -> None:
    with _connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM mcp_activity_ledger LIMIT 1")


async def assert_audit_available() -> None:
    await asyncio.to_thread(_assert_sync)


def _canonical(value: Any) -> str:
    return json.dumps(redact(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _append_sync(event: dict[str, Any]) -> str:
    sanitized = redact(event)
    with _connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(hashtext('mcp_activity_ledger'))")
            cursor.execute("SELECT event_hash FROM mcp_activity_ledger ORDER BY id DESC LIMIT 1")
            row = cursor.fetchone()
            previous_hash = row[0] if row else "0" * 64
            material = f"{previous_hash}:{_canonical(sanitized)}"
            event_hash = hashlib.sha256(material.encode()).hexdigest()
            cursor.execute(
                """
                INSERT INTO mcp_activity_ledger
                (actor_id, actor_type, tenant_id, roles, scopes, environment,
                 correlation_id, causation_id, session_id, policy_decision_id,
                 approval_ids, mcp, tool, arguments, result, duration_ms, status,
                 client_ip, user_agent, previous_hash, event_hash)
                VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s, %s, %s,
                        %s::jsonb, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s, %s, %s, %s)
                """,
                (
                    sanitized["actor_id"],
                    sanitized["actor_type"],
                    sanitized["tenant_id"],
                    _canonical(sanitized.get("roles", [])),
                    _canonical(sanitized.get("scopes", [])),
                    sanitized["environment"],
                    sanitized["correlation_id"],
                    sanitized["causation_id"],
                    sanitized.get("session_id"),
                    sanitized.get("policy_decision_id"),
                    _canonical(sanitized.get("approval_ids", [])),
                    sanitized["mcp"],
                    sanitized["tool"],
                    _canonical(sanitized.get("arguments", {})),
                    _canonical(sanitized.get("result")),
                    sanitized.get("duration_ms"),
                    sanitized["status"],
                    sanitized.get("client_ip"),
                    sanitized.get("user_agent"),
                    previous_hash,
                    event_hash,
                ),
            )
    return event_hash


async def log_tool_call(**event: Any) -> str:
    """Append a sanitized event; failure is propagated so callers fail closed."""
    return await asyncio.to_thread(_append_sync, event)
