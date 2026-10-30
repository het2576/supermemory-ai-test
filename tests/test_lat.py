"""LAT: latency. Protocol: docs/decisions.md D9 (pre-registered at tag `prereg-lat`).

Numbers only. Every test reports DOCUMENTED ("characterized"); the figures are in the notes and in each run's evidence
file as raw per-sample values. Times are seconds from the moment the add call returned, polled from one machine.
"""

from __future__ import annotations

import os

import pytest

from src.adapter import AddOptions, SearchOptions
from src.assertions import canary, scope_id
from src.deletion import wait_done, wait_found
from src.latency import Target, fmt, latency_ms, observe, summarize
from src.runner import RunOutcome, TestContext, TestDef

LAT01_DOCS, LAT03_DOCS = 10, 5
SEARCHES_PER_MODE = 30
QUERIES = [
    "Who is responsible for the vendor contract?",
    "What is the ticket reference?",
    "When does the maintenance window start?",
    "Which city hosts the annual meeting?",
    "What colour is the delivery van?",
]


def _add(ctx: TestContext, scope: str, content: str, dreaming: str | None):
    """Add one document. Returns (doc_id or None, add call ms, error text, origin time)."""
    p = ctx.provider
    r = p.add(scope, content, AddOptions(dreaming=dreaming) if dreaming else None)  # type: ignore[arg-type]
    origin = ctx.clock.now()
    if not r.doc_id:
        return None, None, f"add returned no id (HTTP {r.http_status})", origin
    return r.doc_id, latency_ms(p), "", origin


def _sequential(ctx: TestContext, label: str, n: int, watch: tuple[str, ...], dreaming: str | None, cap_s: float) -> RunOutcome:
    """Shared body of LAT-01 and LAT-03: n documents in one scope, added and timed one at a time at 1s polling."""
    p = ctx.provider
    scope = scope_id(f"memtrust_{label}")
    ctx.track(scope)
    samples: list[dict] = []
    for i in range(n):
        token = canary("LAT")
        doc_id, add_ms, err, origin = _add(ctx, scope, f"Memo {i}: the ticket reference is {token}.", dreaming)
        if doc_id is None:
            return RunOutcome("ERROR", [{"samples": samples}], notes=f"document {i}: {err}")
        t = Target(f"doc{i}", scope, doc_id, token, f"What is the ticket reference in memo {i}?", origin, watch, cap_s)
        observe(p, [t], ctx.clock, interval_s=1)
        samples.append({"i": i, "add_ms": add_ms, **{e: t.seen.get(e) for e in watch}, "failed": t.failed})
    stats = {e: summarize([s[e] for s in samples], total=n) for e in watch}
    if not any(stats[e]["n"] for e in watch):
        return RunOutcome("INCONCLUSIVE", [{"samples": samples}], notes="no document reached any measured event within its cap", extra={"samples": samples, "stats": stats})
    names = {"done": "done", "chunk_hit": "first chunk hit", "dreaming_done": "dreaming done", "memory_hit": "first memory hit"}
    notes = "; ".join(f"{names[e]} {fmt(stats[e])}" for e in watch) + f"; add call {fmt(summarize([s['add_ms'] for s in samples]), 'ms', 0)}"
    return RunOutcome("DOCUMENTED", [{"samples": samples}], notes=notes, extra={"samples": samples, "stats": stats, "dreaming": dreaming or "default"})


# --- LAT-01 ---------------------------------------------------------------------------------


def lat_01(ctx: TestContext) -> RunOutcome:
    """Ingest with the default dreaming mode: time to status done and, separately, to the first chunk-search hit."""
    return _sequential(ctx, "lat01", LAT01_DOCS, ("done", "chunk_hit"), None, cap_s=120)


# --- LAT-02 ---------------------------------------------------------------------------------


def lat_02(ctx: TestContext) -> RunOutcome:
    """Search round trip per mode, sequential, from the HTTP exchange. The very first search is the 'cold' call."""
    p = ctx.provider
    if getattr(p, "last_latency_ms", None) is None:
        return RunOutcome("SKIPPED", notes="provider cannot report per-call latency")
    scope = scope_id("memtrust_lat02")
    ctx.track(scope)
    cps: list = []
    topics = [
        "The vendor contract is owned by Tamsin from procurement.",
        "The ticket reference for the outage is TR-4471.",
        "The maintenance window starts at two in the morning on Sunday.",
        "The annual meeting is held in the city of Lisbon.",
        "The delivery van is painted dark green.",
        "The office printer on the third floor is out of toner.",
    ]
    last_id = None
    for text in topics:
        added = p.add(scope, text, AddOptions(dreaming="instant"))
        if not added.doc_id:
            return RunOutcome("ERROR", cps, notes=f"seed add returned no id (HTTP {added.http_status})")
        last_id = added.doc_id
        ready = wait_done(p, scope, added.doc_id, ctx.clock, timeout_s=300, dreaming=True)
        if not (ready.value and ready.value.status == "done"):
            return RunOutcome("ERROR", cps, notes="a seed document never reached done")
    wait_found(p, scope, "Which city hosts the annual meeting?", ["Lisbon"], ctx.clock, mode="memories", timeout_s=120, interval_s=5)
    cps.append({"step": "seeded", "documents": len(topics), "last_id": last_id})

    cold = p.search(scope, QUERIES[0], SearchOptions(mode="hybrid"))
    cold_ms = latency_ms(p)
    samples: dict[str, list[dict]] = {"chunks": [], "memories": [], "hybrid": []}
    for mode, rows in samples.items():
        for i in range(SEARCHES_PER_MODE):
            res = p.search(scope, QUERIES[i % len(QUERIES)], SearchOptions(mode=mode))  # type: ignore[arg-type]
            rows.append({"i": i, "ms": latency_ms(p), "http": res.http_status, "hits": len(res.hits)})
    stats = {m: summarize([r["ms"] if r["http"] == 200 else None for r in rows], total=len(rows)) for m, rows in samples.items()}
    errors = {m: sum(1 for r in rows if r["http"] != 200) for m, rows in samples.items()}
    if not any(s["n"] for s in stats.values()):
        return RunOutcome("INCONCLUSIVE", cps, notes="no search returned HTTP 200", extra={"samples": samples})
    notes = f"cold {cold_ms:.0f}ms (HTTP {cold.http_status}); " + "; ".join(f"{m} {fmt(s, 'ms', 0)}" for m, s in stats.items())
    if any(errors.values()):
        notes += f"; non-200 responses: {errors}"
    return RunOutcome("DOCUMENTED", cps, notes=notes, extra={"cold_ms": cold_ms, "samples": samples, "stats": stats, "errors": errors})


# --- LAT-03 ---------------------------------------------------------------------------------


def lat_03(ctx: TestContext) -> RunOutcome:
    """Instant dreaming: time to done, to dreamingStatus done, and to the first memory-search hit."""
    return _sequential(ctx, "lat03", LAT03_DOCS, ("done", "dreaming_done", "memory_hit"), "instant", cap_s=300)


# --- LAT-04 ---------------------------------------------------------------------------------


def lat_04(ctx: TestContext) -> RunOutcome:
    """Default (dynamic) dreaming, three namespaces at once. A and B hold one document each; C holds three related
    documents about one subject, to test the docs' 'batches related docs'. Runs once; raw values, no percentiles."""
    p = ctx.provider
    cap_s = float(os.environ.get("MEMTRUST_LAT04_CAP_S", "1800"))  # shortened only for plumbing pilots
    interval_s = float(os.environ.get("MEMTRUST_LAT04_INTERVAL_S", "15"))
    plan = {
        "A": ["Odalys keeps the spare key to the archive room in a blue tin."],
        "B": ["Bertrand drives a rented truck on the northern delivery route."],
        "C": [
            "The harbour survey team is led by Rosalind.",
            "A survey boat belonging to Rosalind is moored at the east pier.",
            "Every Friday Rosalind files the survey report.",
        ],
    }
    targets: list[Target] = []
    cps: list = []
    for label, texts in plan.items():
        scope = scope_id(f"memtrust_lat04{label.lower()}")
        ctx.track(scope)
        for k, text in enumerate(texts):
            token = canary("LAT")
            body = text.replace(".", f" (ref {token}).", 1)
            doc_id, add_ms, err, origin = _add(ctx, scope, body, None)
            if doc_id is None:
                return RunOutcome("ERROR", cps, notes=f"scope {label} document {k}: {err}")
            targets.append(Target(f"{label}{k + 1}", scope, doc_id, token, text.rstrip("."), origin, ("done", "dreaming_done", "memory_hit"), cap_s))
    cps.append({"step": "added", "documents": len(targets), "cap_s": cap_s, "interval_s": interval_s})
    observe(p, targets, ctx.clock, interval_s=interval_s)

    rows = [{"doc": t.label, "scope_group": t.label[0], **{e: t.seen.get(e) for e in t.watch}, "capped": t.capped, "failed": t.failed} for t in targets]
    if not any(r["done"] is not None for r in rows):
        return RunOutcome("INCONCLUSIVE", cps, notes="no document reached done within the cap", extra={"rows": rows, "cap_s": cap_s})

    def show(v: float | None) -> str:
        return "not within cap" if v is None else f"{v:.0f}s"

    notes = "; ".join(f"{r['doc']}: done {show(r['done'])}, dreaming {show(r['dreaming_done'])}, memory {show(r['memory_hit'])}" for r in rows) + f" (cap {cap_s:.0f}s)"
    return RunOutcome("DOCUMENTED", cps, notes=notes, extra={"rows": rows, "cap_s": cap_s, "interval_s": interval_s})


LAT_01 = TestDef("LAT-01", "LAT", "Ingest latency, default dreaming", lat_01)
LAT_02 = TestDef("LAT-02", "LAT", "Search latency by mode", lat_02)
LAT_03 = TestDef("LAT-03", "LAT", "Time to memory, instant dreaming", lat_03)
LAT_04 = TestDef("LAT-04", "LAT", "Time to memory, default (dynamic) dreaming", lat_04)

TESTS = [LAT_01, LAT_02, LAT_03, LAT_04]


@pytest.mark.parametrize("test", TESTS, ids=lambda t: t.id)
def test_lat(test, check):
    check(test)
