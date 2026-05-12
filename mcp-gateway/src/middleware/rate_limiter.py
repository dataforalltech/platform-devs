"""Rate limiting middleware using Redis."""
from __future__ import annotations

import time
import redis.asyncio as aioredis
from fastapi import HTTPException

LIMITS = {
    "admin": {"per_second": 100, "per_month": 100_000},
    "developer": {"per_second": 20, "per_month": 10_000},
    "readonly": {"per_second": 5, "per_month": 1_000},
}

_redis = None

async def get_redis():
    """Get or create Redis connection."""
    global _redis
    if _redis is None:
        _redis = await aioredis.from_url("redis://redis:6379", decode_responses=True)
    return _redis

async def check_rate_limit(user_id: str, role: str) -> None:
    """Check if user has exceeded rate limits. Raises HTTPException if over limit."""
    redis = await get_redis()

    limits = LIMITS.get(role, LIMITS["readonly"])

    # Per-second limit
    key_sec = f"rate:{user_id}:{int(time.time())}"
    per_sec = await redis.incr(key_sec)
    await redis.expire(key_sec, 2)

    if per_sec > limits["per_second"]:
        raise HTTPException(429, "Rate limit exceeded (per second)")

    # Per-month limit
    now = time.time()
    month_key = f"quota:{user_id}:{int(now // 2592000)}"
    per_month = await redis.incr(month_key)
    await redis.expire(month_key, 2592000)  # 30 days

    if per_month > limits["per_month"]:
        raise HTTPException(429, "Monthly quota exceeded")

async def close_redis():
    """Close Redis connection."""
    global _redis
    if _redis:
        await _redis.close()
