"""Application settings (pydantic-settings).

Single source of runtime configuration for the dev agent PoC. Values can be
overridden via environment variables prefixed ``DEV_`` (see ``model_config``),
e.g. ``DEV_GATEWAY_URL``, ``DEV_TOOL_MAX_RETRIES``.

Design notes (from the senior critique):

- ``resume_writes_safe`` defaults to ``False`` (critique §1.9 / §4): the
  platform-mcp gateway does NOT deduplicate writes by ``Idempotency-Key``
  (it only retries reads). Until that contract is proven, resuming a write is
  unsafe and is the executor's responsibility (out of this skeleton). Reads
  are always safe to resume/retry.
- Per-run ceilings (critique §2.1/§2.2) bound autonomous cost/latency:
  ``max_tokens``, ``max_wall_clock_s``, ``max_tool_calls`` (and a plan
  fan-out cap ``max_plan_items``). These are enforced by the run loop /
  executor (out of this skeleton), but the limits live here so there is one
  authority.

There are no phantom names here: every field maps to a concrete behaviour
consumed elsewhere in the codebase or explicitly reserved for the executor.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings for the dev agent.

    Environment variables use the ``DEV_`` prefix. Example::

        DEV_GATEWAY_URL=https://platform-mcp.example.com/mcp
        DEV_TOOL_MAX_RETRIES=5
    """

    model_config = SettingsConfigDict(
        env_prefix="DEV_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Gateway (platform-mcp, Streamable HTTP + OAuth) ---
    gateway_url: str = Field(
        default="http://localhost:8080/mcp",
        description="Base URL of the platform-mcp gateway (Streamable HTTP endpoint).",
    )
    connect_timeout_s: float = Field(
        default=5.0,
        gt=0,
        description="TCP/connect timeout for a single gateway request, in seconds.",
    )
    read_timeout_s: float = Field(
        default=120.0,
        gt=0,
        description="Read timeout for a single gateway request, in seconds.",
    )
    write_timeout_s: float = Field(
        default=10.0,
        gt=0,
        description="Write timeout for a single gateway request, in seconds.",
    )

    # --- Retry policy (reads only; see GatewayToolClient) ---
    tool_max_retries: int = Field(
        default=3,
        ge=1,
        description=(
            "Max attempts for a READ tool call via the gateway (tenacity). "
            "Writes are never retried here (see resume_writes_safe)."
        ),
    )
    retry_backoff_min_s: float = Field(
        default=1.0,
        ge=0,
        description="Exponential backoff lower bound between read retries, in seconds.",
    )
    retry_backoff_max_s: float = Field(
        default=10.0,
        gt=0,
        description="Exponential backoff upper bound between read retries, in seconds.",
    )

    # --- Idempotency / resume safety (critique §1.9) ---
    resume_writes_safe: bool = Field(
        default=False,
        description=(
            "Whether the gateway deduplicates writes by Idempotency-Key. When "
            "False, the executor MUST NOT resume/retry write items (would "
            "duplicate the side effect). Kept False until proven (critique §4)."
        ),
    )

    # --- Per-run ceilings (critique §2.1/§2.2) ---
    max_tokens: int = Field(
        default=200_000,
        gt=0,
        description="Hard ceiling on LLM tokens consumed by a single run.",
    )
    max_wall_clock_s: float = Field(
        default=1800.0,
        gt=0,
        description="Hard ceiling on wall-clock seconds for a single run.",
    )
    max_tool_calls: int = Field(
        default=200,
        gt=0,
        description="Hard ceiling on gateway tool calls performed by a single run.",
    )
    max_plan_items: int = Field(
        default=100,
        gt=0,
        description="Fan-out cap: a plan with more items than this is rejected.",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached ``Settings`` instance (read env once per process)."""
    return Settings()
