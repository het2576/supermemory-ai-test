"""Shared building blocks for the LAT tests. Protocol: docs/decisions.md D9 (pre-registered, tag `prereg-lat`)."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Sequence

from .adapter import MemoryProvider, SearchOptions
from .clock import Clock


def percentile(values: Sequence[float], q: float) -> float | None:
    """Nearest-rank percentile: the value at rank ceil(q * n) of the sorted samples. None for no samples."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(1, math.ceil(q * len(ordered))) - 1]


def summarize(values: Sequence[float | None], *, total: int | None = None) -> dict[str, Any]:
    """n counts samples that produced a number; n_total includes the ones that did not (never silently dropped)."""
    got = [v for v in values if v is not None]
    n_total = total if total is not None else len(values)
    return {
        "n": len(got),
        "n_total": n_total,
        "min": min(got) if got else None,
        "p50": percentile(got, 0.50),
        "p95": percentile(got, 0.95),
        "p95_is_max": len(got) < 20,  # with fewer than 20 samples the 95th percentile is the maximum
        "max": max(got) if got else None,
    }


def fmt(stats: dict[str, Any], unit: str = "s", digits: int = 1) -> str:
    if not stats["n"]:
        return f"no sample (0/{stats['n_total']})"
    f = lambda v: f"{v:.{digits}f}{unit}"  # noqa: E731
    p95 = f"{f(stats['p95'])}{'*' if stats['p95_is_max'] else ''}"
    miss = f", {stats['n_total'] - stats['n']} not within cap" if stats["n"] < stats["n_total"] else ""
    return f"p50 {f(stats['p50'])} p95 {p95} max {f(stats['max'])} (n={stats['n']}{miss})"


@dataclass
class Target:
    """One document to watch. `watch` lists the events to time, in seconds from `origin` (the moment add returned)."""

    label: str
    scope: str
    doc_id: str
    token: str
    query: str
    origin: float
    watch: tuple[str, ...]  # any of: done, dreaming_done, chunk_hit, memory_hit
    cap_s: float
    seen: dict[str, float] = field(default_factory=dict)
    failed: bool = False
    capped: bool = False

    def pending(self) -> list[str]:
        return [e for e in self.watch if e not in self.seen]


def observe(p: MemoryProvider, targets: list[Target], clock: Clock, *, interval_s: float) -> None:
    """Poll every target until each has seen all its events, failed, or hit its cap. An event is stamped when the
    poll that observed it returns, so every time carries roughly one call's latency of upward bias."""
    while True:
        for t in targets:
            pending = t.pending()
            if not pending or t.failed or t.capped:
                continue
            if "done" in pending or "dreaming_done" in pending:
                s = p.status(t.scope, t.doc_id)
                stamp = clock.now() - t.origin
                if s is not None and s.status == "failed":
                    t.failed = True
                    continue
                if s is not None and s.status == "done":
                    t.seen.setdefault("done", stamp)
                    if s.dreaming_status == "done":
                        t.seen.setdefault("dreaming_done", stamp)
            for event, mode in (("chunk_hit", "chunks"), ("memory_hit", "memories")):
                if event in pending and event not in t.seen:
                    hits = p.search(t.scope, t.query, SearchOptions(mode=mode)).hits  # type: ignore[arg-type]
                    stamp = clock.now() - t.origin
                    if any(t.token in h.text for h in hits):
                        t.seen[event] = stamp
            if t.pending() and clock.now() - t.origin >= t.cap_s:
                t.capped = True
        if all(not t.pending() or t.failed or t.capped for t in targets):
            return
        clock.sleep(interval_s)


def latency_ms(p: MemoryProvider) -> float | None:
    fn = getattr(p, "last_latency_ms", None)
    return fn() if fn else None
