"""Deterministic intent -> runbook_id selection (critique §1.3).

``_detect_profile`` yields ``action_mode="plan"`` but not a ``runbook_id``;
``PlanBuilder.build_from_runbook`` needs one. This module closes that gap with a
**deterministic** map from a normalized ``(entity_type | sub_intent)`` key to a
runbook id, over a **CLOSED enum**: every target id is validated against
``RUNBOOK_CATALOG`` at import time, so the selector can never point at a runbook
that does not exist.

An optional LLM fallback is injectable (not required). It, too, is constrained
to the closed set of catalog ids; anything outside the set is rejected and the
selector returns ``None`` (the caller decides what to do with no match — e.g.
ask the user or fall back to analyze mode).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol

from app.dev_agent.runbook.catalog import RUNBOOK_CATALOG


def _normalize(value: str | None) -> str:
    """Normalize a routing token: strip, lower-case, spaces/dashes -> underscore."""
    if not value:
        return ""
    return value.strip().lower().replace("-", "_").replace(" ", "_")


# Deterministic routing map. Keys are normalized entity_type / sub_intent
# tokens; values MUST be ids that exist in RUNBOOK_CATALOG (closed enum,
# asserted below). Add a row here when a new runbook is introduced.
_ROUTES: dict[str, str] = {
    # entity_type-style keys
    "service_health": "health_to_report",
    "health_report": "health_to_report",
    "qa_report": "health_to_report",
    # sub_intent-style keys
    "check_health": "health_to_report",
    "run_tests": "health_to_report",
    "health_check": "health_to_report",
}


class RunbookSelectorLLM(Protocol):
    """Optional LLM fallback: pick a runbook id from the closed set.

    The implementation is injected and returns a string that MUST be one of the
    ids in ``allowed`` (the closed enum). The selector validates the return and
    discards anything outside the set.
    """

    def select_runbook(
        self, *, intent: str, entity_type: str | None, sub_intent: str, allowed: Sequence[str]
    ) -> str | None: ...


class RunbookSelector:
    """Deterministic (entity_type|sub_intent) -> runbook_id, over a closed enum."""

    def __init__(
        self,
        *,
        routes: dict[str, str] | None = None,
        llm_fallback: RunbookSelectorLLM | None = None,
    ) -> None:
        self._routes = dict(routes) if routes is not None else dict(_ROUTES)
        self._allowed = frozenset(RUNBOOK_CATALOG)
        # CLOSED enum: every configured route target must exist in the catalog.
        unknown = {rid for rid in self._routes.values() if rid not in self._allowed}
        if unknown:
            raise ValueError(
                f"RunbookSelector routes point at unknown runbook(s): {sorted(unknown)}; "
                f"available: {sorted(self._allowed)}"
            )
        self._llm_fallback = llm_fallback

    @property
    def allowed(self) -> frozenset[str]:
        return self._allowed

    def select(
        self,
        *,
        intent: str,
        entity_type: str | None,
        sub_intent: str,
    ) -> str | None:
        """Return the runbook id for the given routing tokens, or ``None``.

        Deterministic first: try the normalized ``entity_type`` then the
        normalized ``sub_intent``. If neither matches and an LLM fallback was
        injected, ask it — but only accept a reply inside the closed enum.
        No match => ``None`` (the caller handles it).
        """
        for token in (_normalize(entity_type), _normalize(sub_intent)):
            if token and token in self._routes:
                return self._routes[token]

        if self._llm_fallback is not None:
            choice = self._llm_fallback.select_runbook(
                intent=intent,
                entity_type=entity_type,
                sub_intent=sub_intent,
                allowed=sorted(self._allowed),
            )
            if choice in self._allowed:  # reject anything outside the closed set
                return choice

        return None


__all__ = ["RunbookSelector", "RunbookSelectorLLM"]
