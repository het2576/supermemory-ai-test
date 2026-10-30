"""The single add -> wait -> search -> delete -> confirm-gone cycle.

This is a harness check, not DEL-01. It is used by scripts/smoke.py against the real API (output is
excluded from results, decisions.md D1) and by selftest/ against the mock. The verdict thresholds are
the pre-registered deletion ones in docs/guarantees-matrix.md section 2.1.
"""

from __future__ import annotations

from .adapter import MemoryProvider, SearchOptions
from .assertions import canary, contains_canary, scope_id
from .clock import Clock, RealClock
from .runner import RunOutcome
from .wait import at_checkpoints, poll_until

DELETE_CHECKPOINTS_S = (0, 5, 30, 120, 300, 600)
PASS_WITHIN_S = 120
SLOW_WITHIN_S = 600
READY_TIMEOUT_S = 120


def run_cycle(provider: MemoryProvider, clock: Clock | None = None, scope: str | None = None, log=lambda s: None) -> RunOutcome:
    clock = clock or RealClock()
    scope = scope or scope_id("memtrust_smoke")
    c = canary("CYCLE")
    query = "What is the marker for the cycle note?"
    cp: list[dict] = []
    t0 = clock.now()

    def stamp() -> str:
        return f"[{clock.now() - t0:6.1f}s]"

    try:
        added = provider.add(scope, f"Cycle note. The marker for this note is {c}.")
        log(f"{stamp()} add -> HTTP {added.http_status} id={added.doc_id!r} body={added.raw}")
        if not added.doc_id:
            return RunOutcome("ERROR", cp, notes=f"add returned no id (HTTP {added.http_status})")

        ready = poll_until(
            lambda: provider.status(scope, added.doc_id),
            lambda s: s is not None and s.status in ("done", "failed"),
            timeout_s=READY_TIMEOUT_S,
            clock=clock,
        )
        state = ready.value.status if ready.value else "missing"
        log(f"{stamp()} status -> {state} after {ready.elapsed_s:.1f}s")
        cp.append({"step": "status_done", "elapsed_s": ready.elapsed_s, "status": state})
        if state != "done":
            return RunOutcome("ERROR", cp, notes=f"document never reached done (last status: {state})")

        found = poll_until(
            lambda: provider.search(scope, query, SearchOptions(mode="hybrid")),
            lambda r: contains_canary(r.hits, c),
            timeout_s=READY_TIMEOUT_S,
            clock=clock,
        )
        top = found.value.hits[0] if found.value and found.value.hits else None
        log(f"{stamp()} search found canary: {found.ok} after {found.elapsed_s:.1f}s; top score={top.score if top else None}")
        cp.append({"step": "searchable", "elapsed_s": found.elapsed_s, "found": found.ok})
        if not found.ok:
            return RunOutcome("ERROR", cp, notes="canary not searchable within 120s; cannot test deletion")

        deleted = provider.delete(scope, [added.doc_id])
        log(f"{stamp()} delete -> HTTP {deleted.http_status} count={deleted.count} errors={deleted.errors}")
        cp.append({"step": "delete", "count": deleted.count, "errors": deleted.errors})
        if deleted.count != 1 or deleted.errors:
            return RunOutcome("ERROR", cp, notes=f"delete not accepted: count={deleted.count} errors={deleted.errors}")

        checks = at_checkpoints(
            lambda: contains_canary(provider.search(scope, query, SearchOptions(mode="hybrid")).hits, c),
            DELETE_CHECKPOINTS_S,
            stop_when=lambda present: not present,
            clock=clock,
        )
        for k in checks:
            cp.append({"t": k.t, "canaryPresent": k.value})
            log(f"{stamp()} checkpoint t={k.t:>4}s canary present: {k.value}")

        gone_at = next((k.t for k in checks if not k.value), None)
        if gone_at is not None and gone_at <= PASS_WITHIN_S:
            return RunOutcome("PASS", cp, time_to_consistency_s=gone_at)
        if gone_at is not None and gone_at <= SLOW_WITHIN_S:
            return RunOutcome("SLOW", cp, time_to_consistency_s=gone_at, notes=f"gone at {gone_at}s")
        return RunOutcome("FAIL", cp, notes=f"canary still present at {DELETE_CHECKPOINTS_S[-1]}s after delete")
    finally:
        try:
            provider.delete_scope(scope)
        except Exception:
            pass
