"""Shared building blocks for the DEL tests. Rules: docs/guarantees-matrix.md section 2.1 + amendment A1."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .adapter import AddOptions, MemoryProvider, SearchOptions
from .clock import Clock
from .runner import Verdict
from .wait import PollResult, poll_until

MODES = ("chunks", "memories", "hybrid")
SCHEDULE_S = (0, 5, 30, 120, 300, 600)  # pre-registered checkpoints, measured from the delete call returning
PASS_WITHIN_S = 120
SLOW_WITHIN_S = 600
CONFIRM_AFTER_S = 10  # amendment A1: a first absence must hold on one more probe
READY_TIMEOUT_S = 120


def present_surfaces(
    provider: MemoryProvider,
    scope: str,
    query: str,
    markers: list[str],
    *,
    modes: tuple[str, ...] = MODES,
    profile: bool = False,
) -> list[str]:
    """Names of the normal retrieval surfaces that still return any marker. Empty list = gone everywhere."""
    found: list[str] = []
    for mode in modes:
        hits = provider.search(scope, query, SearchOptions(mode=mode)).hits  # type: ignore[arg-type]
        if any(m in h.text for h in hits for m in markers):
            found.append(f"search:{mode}")
    if profile and provider.capabilities().profiles:
        entries = provider.profile(scope).entries
        if any(m in e for e in entries for m in markers):
            found.append("profile")
    return found


def wait_done(provider: MemoryProvider, scope: str, doc_id: str, clock: Clock, *, timeout_s: float = READY_TIMEOUT_S, dreaming: bool = False) -> PollResult:
    def ready(s) -> bool:
        if s is None:
            return False
        if s.status == "failed":
            return True
        return s.status == "done" and (not dreaming or s.dreaming_status == "done")

    return poll_until(lambda: provider.status(scope, doc_id), ready, interval_s=2 if not dreaming else 5, timeout_s=timeout_s, clock=clock)


def wait_found(provider: MemoryProvider, scope: str, query: str, markers: list[str], clock: Clock, *, mode: str = "hybrid", timeout_s: float = READY_TIMEOUT_S, interval_s: float = 2) -> PollResult:
    def probe() -> bool:
        hits = provider.search(scope, query, SearchOptions(mode=mode)).hits  # type: ignore[arg-type]
        return any(m in h.text for h in hits for m in markers)

    return poll_until(probe, bool, interval_s=interval_s, timeout_s=timeout_s, clock=clock)


@dataclass
class Watch:
    gone_at: float | None
    checkpoints: list[dict[str, Any]]
    reappeared: bool


def watch_until_gone(probe, clock: Clock, schedule=SCHEDULE_S, confirm_after_s: float = CONFIRM_AFTER_S) -> Watch:
    """probe() returns the list of surfaces still showing the content. First checkpoint with an empty list,
    held on a confirming probe, is the time-to-consistency. A reappearance is recorded and the watch continues."""
    start = clock.now()
    cps: list[dict[str, Any]] = []
    reappeared = False
    for t in schedule:
        clock.sleep(start + t - clock.now())
        present = probe()
        cps.append({"t": t, "canaryPresent": bool(present), "surfaces": present})
        if present:
            continue
        clock.sleep(confirm_after_s)
        again = probe()
        cps.append({"t": t + confirm_after_s, "confirm": True, "canaryPresent": bool(again), "surfaces": again})
        if not again:
            return Watch(float(t), cps, reappeared)
        reappeared = True
    return Watch(None, cps, reappeared)


def deletion_verdict(gone_at: float | None) -> Verdict:
    if gone_at is None:
        return "FAIL"
    if gone_at <= PASS_WITHIN_S:
        return "PASS"
    if gone_at <= SLOW_WITHIN_S:
        return "SLOW"
    return "FAIL"


def add_doc(provider: MemoryProvider, scope: str, content: str, **opts: Any):
    return provider.add(scope, content, AddOptions(**opts))
