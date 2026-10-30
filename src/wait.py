"""Polling and checkpoint helpers. A delay is not a failure: callers report time-to-consistency."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Generic, Sequence, TypeVar

from .clock import Clock, RealClock

T = TypeVar("T")

DEFAULT_CHECKPOINTS_SEC: tuple[float, ...] = (0, 5, 30, 120)


@dataclass
class PollResult(Generic[T]):
    ok: bool
    elapsed_s: float
    value: T | None


def poll_until(
    fn: Callable[[], T],
    done: Callable[[T], bool],
    *,
    interval_s: float = 1.0,
    timeout_s: float = 120.0,
    clock: Clock | None = None,
) -> PollResult[T]:
    """Call fn every interval_s until done(value) is true or timeout_s passes."""
    clock = clock or RealClock()
    start = clock.now()
    while True:
        value = fn()
        elapsed = clock.now() - start
        if done(value):
            return PollResult(True, elapsed, value)
        if elapsed + interval_s > timeout_s:
            return PollResult(False, elapsed, value)
        clock.sleep(interval_s)


@dataclass
class Checkpoint(Generic[T]):
    t: float
    value: T


def at_checkpoints(
    probe: Callable[[], T],
    checkpoints_s: Sequence[float] = DEFAULT_CHECKPOINTS_SEC,
    *,
    stop_when: Callable[[T], bool] | None = None,
    clock: Clock | None = None,
) -> list[Checkpoint[T]]:
    """Run probe at each checkpoint (seconds after the call). Stops early once stop_when is true."""
    clock = clock or RealClock()
    start = clock.now()
    out: list[Checkpoint[T]] = []
    for t in checkpoints_s:
        clock.sleep(start + t - clock.now())
        value = probe()
        out.append(Checkpoint(t, value))
        if stop_when and stop_when(value):
            break
    return out
