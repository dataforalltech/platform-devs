"""Unit tests for RunBudget (per-run tokens / wall-clock / tool-call ceilings).

The wall-clock ceiling is exercised with a fake, hand-advanced clock so the test
never sleeps (critique §2.1: the clock is injectable precisely for this).
"""

from __future__ import annotations

import pytest

from app.dev_agent.budget import BudgetExceeded, RunBudget


class _FakeClock:
    """Manually advanced monotonic clock."""

    def __init__(self) -> None:
        self._t = 0.0

    def __call__(self) -> float:
        return self._t

    def advance(self, seconds: float) -> None:
        self._t += seconds


def test_charge_and_remaining() -> None:
    clock = _FakeClock()
    budget = RunBudget(
        max_tokens=100,
        max_wall_clock_s=60.0,
        max_tool_calls=5,
        clock=clock,
    )
    budget.start()

    budget.charge_tokens(30)
    budget.charge_tool_call()
    budget.charge_tool_call()
    clock.advance(10.0)

    rem = budget.remaining()
    assert rem.tokens == 70
    assert rem.tool_calls == 3
    assert rem.wall_clock_s == pytest.approx(50.0)
    # Still within all ceilings.
    budget.check()


def test_tool_calls_ceiling_trips() -> None:
    budget = RunBudget(max_tokens=1000, max_wall_clock_s=1000.0, max_tool_calls=2)
    budget.start()

    budget.charge_tool_call()
    budget.charge_tool_call()
    budget.check()  # exactly at limit -> still OK

    budget.charge_tool_call()  # one over
    with pytest.raises(BudgetExceeded) as exc:
        budget.check()
    assert exc.value.axis == "tool_calls"
    assert exc.value.limit == 2


def test_tokens_ceiling_trips() -> None:
    budget = RunBudget(max_tokens=50, max_wall_clock_s=1000.0, max_tool_calls=1000)
    budget.start()

    budget.charge_tokens(50)
    budget.check()  # at limit -> OK
    budget.charge_tokens(1)
    with pytest.raises(BudgetExceeded) as exc:
        budget.check()
    assert exc.value.axis == "tokens"


def test_wall_clock_ceiling_trips_with_fake_clock() -> None:
    clock = _FakeClock()
    budget = RunBudget(
        max_tokens=10_000,
        max_wall_clock_s=30.0,
        max_tool_calls=10_000,
        clock=clock,
    )
    budget.start()

    clock.advance(30.0)
    budget.check()  # exactly at limit -> OK
    clock.advance(0.5)  # now over
    with pytest.raises(BudgetExceeded) as exc:
        budget.check()
    assert exc.value.axis == "wall_clock"
    assert exc.value.used == pytest.approx(30.5)


def test_remaining_floors_at_zero() -> None:
    budget = RunBudget(max_tokens=10, max_wall_clock_s=5.0, max_tool_calls=1)
    budget.start()
    budget.charge_tokens(100)
    budget.charge_tool_call()
    budget.charge_tool_call()
    rem = budget.remaining()
    assert rem.tokens == 0
    assert rem.tool_calls == 0
