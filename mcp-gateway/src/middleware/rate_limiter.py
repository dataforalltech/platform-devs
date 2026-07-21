"""Fail-closed, configuration-driven rate limiting backed by Redis."""
from __future__ import annotations

import json
import os
import time
from typing import Any

import redis.asyncio as aioredis
from fastapi import HTTPException

_redis = None


def _required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ConnectionError(f"{name} is required")
    return value


def _limits() -> dict[str, dict[str, int]]:
    raw = _required("GATEWAY_RATE_LIMITS_JSON")
    try:
        parsed: Any = json.loads(raw)
        if not isinstance(parsed, dict) or not parsed:
            raise ValueError("limits must be a non-empty object")
        for role, limits in parsed.items():
            if not isinstance(role, str) or not isinstance(limits, dict):
                raise ValueError("invalid role limits")
            for key in ("per_second", "per_month"):
                if not isinstance(limits.get(key), int) or limits[key] < 1:
                    raise ValueError(f"invalid {key} limit for {role}")
        return parsed
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        raise ConnectionError("GATEWAY_RATE_LIMITS_JSON is invalid") from exc


async def get_redis():
    global _redis
    if _redis is None:
        host = _required("REDIS_HOST")
        port = int(_required("REDIS_PORT"))
        password = _required("REDIS_PASSWORD")
        database = int(os.environ.get("REDIS_DB", "3"))
        _redis = await aioredis.from_url(
            f"redis://:{password}@{host}:{port}/{database}",
            decode_responses=True,
            socket_connect_timeout=3,
        )
    return _redis


async def check_rate_limit(user_id: str, role: str) -> None:
    limits_by_role = _limits()
    limits = limits_by_role.get(role) or limits_by_role.get("default")
    if limits is None:
        raise ConnectionError(f"no rate limit policy for role {role}")
    redis = await get_redis()

    key_sec = f"rate:{user_id}:{int(time.time())}"
    per_sec = await redis.incr(key_sec)
    await redis.expire(key_sec, 2)
    if per_sec > limits["per_second"]:
        raise HTTPException(429, "Rate limit exceeded (per second)")

    month_key = f"quota:{user_id}:{int(time.time() // 2592000)}"
    per_month = await redis.incr(month_key)
    await redis.expire(month_key, 2592000)
    if per_month > limits["per_month"]:
        raise HTTPException(429, "Monthly quota exceeded")


async def close_redis() -> None:
    global _redis
    if _redis:
        await _redis.aclose()
        _redis = None
