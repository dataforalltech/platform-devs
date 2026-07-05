"""Per-run resource budget (critique §2.1).

An autonomous run has no natural stopping point: N plan items, each a ReAct
persona of up to ~15 iterations, each tool returning arbitrarily large payloads
=> unbounded cost and wall-clock. Per-chunk stream timeouts protect latency, not
the total. :class:`RunBudget` bounds a single run along three axes at once:

- ``max_tokens``       — cumulative LLM tokens charged to the run;
- ``max_wall_clock_s`` — elapsed wall-clock since :meth:`start`;
- ``max_tool_calls``   — number of gateway tool calls.

The executor charges a tool call and calls :meth:`check` BEFORE dispatching, so a
budget that is already spent stops the run cleanly (remaining items skipped)
instead of paying for one more call. The clock is injectable (defaults to
``time.monotonic``) so the wall-clock ceiling is testable without sleeping.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass


class BudgetExceeded(RuntimeError):
    """A run exceeded one of its budget ceilings.

    ``axis`` names which ceiling tripped (``"tokens"`` / ``"wall_clock"`` /
    ``"tool_calls"``); ``used`` / ``limit`` are the offending values.
    """

    def __init__(self, axis: str, used: float, limit: float) -> None:
        self.axis = axis
        self.used = used
        self.limit = limit
        super().__init__(
            f"run budget exceeded on {axis}: used={used} > limit={limit}"
        )


@dataclass
class BudgetSnapshot:
    """Remaining headroom on each axis (see :meth:`RunBudget.remaining`)."""

    tokens: int
    wall_clock_s: float
    tool_calls: int


class RunBudget:
    """A three-axis ceiling for one run.

    Charges accumulate via :meth:`charge_tokens` / :meth:`charge_tool_call`;
    :meth:`check` raises :class:`BudgetExceeded` the moment any axis is over its
    limit. ``clock`` is injectable purely so wall-clock can be tested without a
    real sleep — production uses the default ``time.monotonic``.
    """

    def __init__(
        self,
        max_tokens: int,
        max_wall_clock_s: float,
        max_tool_calls: int,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max_tokens = max_tokens
        self._max_wall_clock_s = max_wall_clock_s
        self._max_tool_calls = max_tool_calls
        self._clock = clock

        self._tokens_used = 0
        self._tool_calls_used = 0
        self._started_at: float | None = None

    def start(self) -> None:
        """Mark the run's start (anchors the wall-clock ceiling). Idempotent-ish:

        calling it again re-anchors the clock to *now* — call it exactly once at
        the top of a run.
        """
        self._started_at = self._clock()

    def charge_tokens(self, n: int) -> None:
        """Add ``n`` LLM tokens to the running total (does not itself raise)."""
        if n < 0:
            raise ValueError("token charge must be non-negative")
        self._tokens_used += n

    def charge_tool_call(self) -> None:
        """Count one gateway tool call (does not itself raise; see :meth:`check`)."""
        self._tool_calls_used += 1

    def _elapsed(self) -> float:
        if self._started_at is None:
            return 0.0
        return self._clock() - self._started_at

    def check(self) -> None:
        """Raise :class:`BudgetExceeded` if any axis is over its ceiling.

        Checked in a stable order (tokens, tool calls, wall-clock) so the
        reported axis is deterministic when more than one is over at once.
        """
        if self._tokens_used > self._max_tokens:
            raise BudgetExceeded("tokens", self._tokens_used, self._max_tokens)
        if self._tool_calls_used > self._max_tool_calls:
            raise BudgetExceeded(
                "tool_calls", self._tool_calls_used, self._max_tool_calls
            )
        elapsed = self._elapsed()
        if elapsed > self._max_wall_clock_s:
            raise BudgetExceeded("wall_clock", elapsed, self._max_wall_clock_s)

    def remaining(self) -> BudgetSnapshot:
        """Return headroom left on each axis (floored at zero)."""
        return BudgetSnapshot(
            tokens=max(0, self._max_tokens - self._tokens_used),
            wall_clock_s=max(0.0, self._max_wall_clock_s - self._elapsed()),
            tool_calls=max(0, self._max_tool_calls - self._tool_calls_used),
        )
