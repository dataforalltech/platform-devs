"""Dev orchestrator — leader/classifier only (walking-skeleton scope).

This module implements *classification* — mapping a user message to a persona
plus routing metadata (:meth:`DevOrchestrator._detect_profile`). It does NOT
implement ``stream()`` / dispatch / full execution; those belong to a later
integration and are intentionally left out (per the walking-skeleton plan).

Corrections baked in (from the senior critique):

- ``confidence`` is enforced in Python (§1.6/§the marketing gotcha): a reply
  below the threshold falls back to ``architecture``, not left to the prompt.
- The intent cache is an INSTANCE dict with a bounded ``maxsize`` and expired-
  entry purging (§1.5): no unbounded class-level dict that leaks for the process
  lifetime.
- ``action_mode`` is validated against the closed set ``{plan, analyze,
  guided_creation}``; anything else becomes ``analyze``.
- The classifier reaches the LLM only through the injected seam
  (:class:`~app.dev_agent.llm.base.LLM`) — no hardcoded provider.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.dev_agent.gateway.tool_provider import GatewayToolProvider, ToolSpec
from app.dev_agent.llm.base import LLM, LLMProvider
from app.dev_agent.profiles.registry import PROFILES

logger = logging.getLogger(__name__)

# Fallback persona when the classifier is uncertain or fails.
FALLBACK_PROFILE = "architecture"
# Confidence below this => fall back (enforced HERE, not in the prompt).
CONFIDENCE_THRESHOLD = 0.6
# Closed set of action modes the classifier may emit.
_ACTION_MODES = frozenset({"plan", "analyze", "guided_creation"})
# Single-shot classifier invocation timeout, in seconds.
LEADER_INVOKE_TIMEOUT_S = 30.0

_INTENT_SYSTEM = """You are a precise intent classifier for an autonomous engineering team.
Return ONLY a single JSON object, no prose, with these keys:
{"profile":"<one of: security|qa_engineer|architecture|backend|frontend|devops|product_owner|product_manager>",
 "sub_intent":"<short sub-intent slug>",
 "intent":"<one sentence>",
 "confidence":<float 0.0-1.0>,
 "action_mode":"plan"|"analyze"|"guided_creation",
 "entity_type":"<entity type or null>"}
Use "architecture" when the request is ambiguous. Set confidence honestly."""


@dataclass
class _CacheEntry:
    """A cached classification plus its absolute expiry (monotonic seconds)."""

    result: tuple[str, str, str, str, str | None]
    expires_at: float


class DevOrchestrator:
    """Leader/classifier for the dev agent (classification only in this phase)."""

    def __init__(
        self,
        *,
        tenant_id: str,
        leader_llm: LLM,
        cache_ttl_s: float = 300.0,
        cache_maxsize: int = 512,
        tool_provider: GatewayToolProvider | None = None,
    ) -> None:
        self._tenant_id = tenant_id
        self._leader_llm = leader_llm  # temperature=0 model, injected via the seam
        self._cache_ttl_s = cache_ttl_s
        self._cache_maxsize = max(1, int(cache_maxsize))
        # INSTANCE cache (not class-level): bounded + purged, no process leak.
        self._intent_cache: dict[str, _CacheEntry] = {}
        # Optional (kept None-defaulting so the classifier tests need no gateway):
        # required only for the `analyze` path, where the persona talks to tools.
        self._tool_provider = tool_provider

    def _cache_key(self, message: str) -> str:
        # Normalize (strip + lower) so trivial variants share a cache slot;
        # scope by tenant so nothing leaks across tenants.
        return f"{self._tenant_id}:{message.strip().lower()}"

    def _cache_get(self, key: str) -> tuple[str, str, str, str, str | None] | None:
        entry = self._intent_cache.get(key)
        if entry is None:
            return None
        if entry.expires_at <= time.monotonic():
            # Expired: drop it so it does not linger.
            self._intent_cache.pop(key, None)
            return None
        return entry.result

    def _cache_put(self, key: str, result: tuple[str, str, str, str, str | None]) -> None:
        now = time.monotonic()
        # Purge expired entries first so the map does not grow unbounded.
        if len(self._intent_cache) >= self._cache_maxsize:
            expired = [k for k, e in self._intent_cache.items() if e.expires_at <= now]
            for k in expired:
                self._intent_cache.pop(k, None)
            # Still over budget after purging expired? Evict oldest-expiring.
            if len(self._intent_cache) >= self._cache_maxsize:
                oldest = min(self._intent_cache, key=lambda k: self._intent_cache[k].expires_at)
                self._intent_cache.pop(oldest, None)
        self._intent_cache[key] = _CacheEntry(
            result=result, expires_at=now + self._cache_ttl_s
        )

    async def _detect_profile(
        self,
        message: str,
        explicit_profile: str | None,
        cb: Any | None = None,
    ) -> tuple[str, str, str, str, str | None]:
        """Classify ``message`` into ``(profile, intent, sub_intent, action_mode, entity_type)``.

        - explicit bypass: a valid ``explicit_profile`` short-circuits the LLM
          (action_mode ``analyze``);
        - otherwise ask the injected leader LLM for JSON and enforce the schema
          in Python (confidence threshold, closed action-mode set, known
          profile), falling back to ``architecture`` / ``analyze`` on any
          violation or error;
        - results are cached with a TTL keyed on the normalized message.
        """
        # Explicit bypass — no LLM call, no cache.
        if explicit_profile and explicit_profile in PROFILES:
            return explicit_profile, message, "", "analyze", None

        key = self._cache_key(message)
        cached = self._cache_get(key)
        if cached is not None:
            return cached

        config = {"callbacks": [cb]} if cb else {}
        try:
            msgs = [
                SystemMessage(content=_INTENT_SYSTEM),
                HumanMessage(content=f"<user_message>\n{message}\n</user_message>"),
            ]
            resp = await asyncio.wait_for(
                self._leader_llm.ainvoke(msgs, config=config),
                timeout=LEADER_INVOKE_TIMEOUT_S,
            )
            result = self._parse_classification(resp, message)
        except Exception:  # noqa: BLE001 - any failure => safe structural fallback
            logger.debug("leader classification failed; falling back", exc_info=True)
            result = (FALLBACK_PROFILE, message[:100], "", "analyze", None)

        self._cache_put(key, result)
        return result

    @staticmethod
    def _parse_classification(
        resp: Any, message: str
    ) -> tuple[str, str, str, str, str | None]:
        """Parse + enforce the leader's JSON reply (confidence, closed sets)."""
        raw = getattr(resp, "content", resp)
        if not isinstance(raw, str):
            raw = str(raw)
        data = json.loads(raw.strip() or "{}")

        profile = data.get("profile", FALLBACK_PROFILE)
        try:
            confidence = float(data.get("confidence", 1.0))
        except (TypeError, ValueError):
            confidence = 0.0
        # Enforce the threshold and known-profile check in Python.
        if profile not in PROFILES or confidence < CONFIDENCE_THRESHOLD:
            profile = FALLBACK_PROFILE

        action_mode = data.get("action_mode", "analyze")
        if action_mode not in _ACTION_MODES:
            action_mode = "analyze"

        intent = data.get("intent") or message[:100]
        sub_intent = data.get("sub_intent") or ""
        entity_type = data.get("entity_type") or None
        return profile, intent, sub_intent, action_mode, entity_type

    async def run_analyze(
        self,
        message: str,
        *,
        profile: str,
        session_id: str,
        tool_specs: Sequence[ToolSpec],
        llm_provider: LLMProvider,
        run_id: str = "run",
        tenant_id: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> AsyncIterator[str]:
        """Stream a persona's ``analyze`` turn: converse over gateway tools.

        The persona named ``profile`` is instantiated with capability-guarded
        tools built for that profile (via the injected
        :class:`~app.dev_agent.gateway.tool_provider.GatewayToolProvider`) and its
        ReAct ``astream`` is relayed token by token. Tools reach the gateway only
        — never a backend directly — and a capability denial surfaces inside the
        loop as a tool error (it never aborts the stream).

        This is the ``analyze`` action-mode only; ``plan`` / ``execute`` live in
        :class:`~app.dev_agent.pipeline.AutonomousPipeline`.
        """
        if self._tool_provider is None:
            raise RuntimeError(
                "run_analyze requires a tool_provider; construct DevOrchestrator "
                "with tool_provider=GatewayToolProvider(...)"
            )
        if profile not in PROFILES:
            raise KeyError(f"unknown persona profile {profile!r}")

        tools = self._tool_provider.build_tools(
            profile_id=profile,
            specs=tool_specs,
            run_id=run_id,
            session_id=session_id,
            tenant_id=tenant_id,
        )
        instance = PROFILES[profile](tools=tools, llm_provider=llm_provider)
        async for token in instance.astream(message, context=context):
            yield token


__all__ = ["DevOrchestrator", "FALLBACK_PROFILE", "CONFIDENCE_THRESHOLD"]
