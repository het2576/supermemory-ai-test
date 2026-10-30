"""Shared building blocks for the COR tests. Rules: docs/decisions.md D8 (pre-registered, tag `prereg-cor`)."""

from __future__ import annotations

import re
from typing import Any, Callable

from .adapter import AddOptions, MemoryProvider, SearchOptions
from .assertions import canary, scope_id
from .clock import Clock
from .deletion import wait_done, wait_found
from .runner import RunOutcome, TestContext

MAX_ATTEMPTS = 3  # same mechanism as amendment A2: the extractor sometimes alters a token, so retry with fresh ones
SETTLE_S = (0, 10, 30, 120)
EARLY_STOP_S = 30  # if every probe up to here was correct, 120s is not needed
PAST_CUE = re.compile(r"\b(used to|previously|formerly|former|before|earlier|was|were|lived|no longer|moved from)\b", re.I)

# (text, tokens that must surface as a current memory right after this document is processed)
Doc = tuple[str, list[str]]


def current_hits(p: MemoryProvider, scope: str, query: str, tokens: list[str]) -> list[dict[str, Any]]:
    """Every place a token is presented as a current memory. A memory hit counts unless it is explicitly isLatest=false.
    Raw chunks never count (D3); they are recorded separately by `chunk_evidence`."""
    found: list[dict[str, Any]] = []
    for mode in ("memories", "hybrid"):
        hits = p.search(scope, query, SearchOptions(mode=mode, include_related=True)).hits  # type: ignore[arg-type]
        memory_hits = [h for h in hits if h.kind == "memory"]
        for rank, h in enumerate(memory_hits):
            for tok in tokens:
                if tok in h.text and h.is_latest is not False:
                    found.append({"token": tok, "surface": f"search:{mode}", "rank": rank, "text": h.text})
    if p.capabilities().profiles:
        for entry in p.profile(scope).entries:
            for tok in tokens:
                if tok in entry:
                    found.append({"token": tok, "surface": "profile", "rank": None, "text": entry})
    return found


def chunk_evidence(p: MemoryProvider, scope: str, query: str, tokens: list[str]) -> dict[str, int | None]:
    """Evidence only: rank of each token in raw chunk results (None = absent). Never decides a verdict."""
    hits = p.search(scope, query, SearchOptions(mode="chunks")).hits
    return {tok: next((i for i, h in enumerate(hits) if tok in h.text), None) for tok in tokens}


def seed_chain(
    ctx: TestContext,
    label: str,
    n_tokens: int,
    make_docs: Callable[[list[str]], list[Doc]],
    query: str,
    cps: list,
    *,
    dreaming: str = "instant",
) -> tuple[str | None, list[str] | None, RunOutcome | None]:
    """Add documents one after another into a fresh scope, proving each stated fact surfaced as a memory before the
    next one is added (otherwise a missing 'old fact' would pass vacuously). Retries with a fresh scope and tokens when
    the extractor alters a token. Returns (scope, tokens, None), or (None, None, outcome) on ERROR or SKIPPED."""
    p, clock = ctx.provider, ctx.clock
    slow = dreaming != "instant"
    reason = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        scope, tokens = scope_id(f"memtrust_{label}"), [canary("COR") for _ in range(n_tokens)]
        ctx.track(scope)
        failed = False
        for i, (text, must_surface) in enumerate(make_docs(tokens)):
            added = p.add(scope, text, AddOptions(dreaming=dreaming))  # type: ignore[arg-type]
            cps.append({"step": f"add_doc{i + 1}", "attempt": attempt, "scope": scope, "http": added.http_status, "id": added.doc_id})
            if not added.doc_id:
                return None, None, RunOutcome("ERROR", cps, notes=f"add of document {i + 1} returned no id (HTTP {added.http_status})")
            ready = wait_done(p, scope, added.doc_id, clock, timeout_s=900 if slow else 300, dreaming=True)
            state = ready.value.status if ready.value else "missing"
            dream = ready.value.dreaming_status if ready.value else None
            cps.append({"step": f"processed_doc{i + 1}", "attempt": attempt, "status": state, "dreaming": dream, "elapsed_s": ready.elapsed_s})
            if state != "done":
                return None, None, RunOutcome("ERROR", cps, notes=f"document {i + 1} never reached done (last status: {state})")
            for tok in must_surface:
                mem = wait_found(p, scope, query, [tok], clock, mode="memories", timeout_s=900 if slow else 120, interval_s=5)
                cps.append({"step": f"memory_for_doc{i + 1}", "attempt": attempt, "token": tok, "found": mem.ok, "elapsed_s": mem.elapsed_s})
                if not mem.ok:
                    reason = f"no memory with the exact token from document {i + 1} surfaced"
                    failed = True
                    break
            if failed:
                break
        if not failed:
            return scope, tokens, None
    return None, None, RunOutcome("SKIPPED", cps, notes=f"{reason} after {MAX_ATTEMPTS} attempts; the update cannot be judged")


def settle(probe: Callable[[], dict[str, Any]], clock: Clock) -> list[dict[str, Any]]:
    """Probe at 0/10/30s; add a 120s probe only if one of the first three was wrong. Each result is {t, ok, ...}."""
    start = clock.now()
    out: list[dict[str, Any]] = []
    for t in SETTLE_S:
        clock.sleep(start + t - clock.now())
        out.append({"t": t, **probe()})
        if t == EARLY_STOP_S and all(c["ok"] for c in out):
            break
    return out


def converged_at(probes: list[dict[str, Any]]) -> float | None:
    """First checkpoint from which every later probe was correct (None if the last one is wrong)."""
    if not probes[-1]["ok"]:
        return None
    t = probes[-1]["t"]
    for c in reversed(probes):
        if not c["ok"]:
            break
        t = c["t"]
    return t


def verdict_from(probes: list[dict[str, Any]], cps: list, extra: dict[str, Any], *, fail_note: str, ok_result: str = "PASS", bad_result: str = "FAIL") -> RunOutcome:
    cps.extend(probes)
    last = probes[-1]
    if last["ok"]:
        at = converged_at(probes)
        note = "" if at == 0 else f"correct only from t={at:g}s (early probes were wrong)"
        return RunOutcome(ok_result, cps, notes=note, extra={**extra, "converged_at_s": at})
    return RunOutcome(bad_result, cps, notes=f"{fail_note} at t={last['t']:g}s: {last.get('problem', '')}", extra={**extra, "converged_at_s": None})


def judge_update(p: MemoryProvider, scope: str, query: str, new: str, old: list[str], *, rank_tolerant: bool = False) -> dict[str, Any]:
    """new must be current; no old token may be current, except (rank_tolerant) a stale search hit that ranks below the new one."""
    now = current_hits(p, scope, query, [new] + old)
    new_hits = [h for h in now if h["token"] == new and h["surface"] == "search:memories"]
    stale = [h for h in now if h["token"] in old]
    new_rank = min((h["rank"] for h in new_hits), default=None)
    new_rank_on = {h["surface"]: h["rank"] for h in sorted((h for h in now if h["token"] == new and h["rank"] is not None), key=lambda h: -h["rank"])}

    def tolerated(h: dict[str, Any]) -> bool:
        """COR-02 only: the profile is not ranked (a note), and a stale search hit is fine if the new fact outranks it there."""
        if not rank_tolerant:
            return False
        if h["surface"] == "profile":
            return True
        return h["surface"] in new_rank_on and h["rank"] > new_rank_on[h["surface"]]

    blocking = [h for h in stale if not tolerated(h)]
    problems = []
    if not new_hits:
        problems.append("the new fact is not current in memory search")
    problems += [f"{h['token']} is still current via {h['surface']}" + (f" (rank {h['rank']} vs new {new_rank})" if h["rank"] is not None else "") for h in blocking]
    return {
        "ok": not problems,
        "problem": "; ".join(problems),
        "new_rank": new_rank,
        "stale": [{k: h[k] for k in ("token", "surface", "rank")} for h in stale],
        "profile_has_new": any(h["token"] == new and h["surface"] == "profile" for h in now),
        "chunks": chunk_evidence(p, scope, query, [new] + old),
    }
