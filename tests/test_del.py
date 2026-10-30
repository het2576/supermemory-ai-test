"""DEL: deletion honoring. Rules: docs/guarantees-matrix.md section 2.1 and amendment A1.

Every test: fresh scope, unique canary, precondition checks (so a pass is meaningful), then the
pre-registered checkpoints 0/5/30/120/300/600s counted from the delete call returning.
`pytest tests/test_del.py` runs them 3x each against the real API; `python -m src.runner --only DEL` does the same.
"""

from __future__ import annotations

import pytest

from src.adapter import AddOptions, SearchOptions
from src.assertions import canary, scope_id
from src.deletion import (
    Watch,
    deletion_verdict,
    present_surfaces,
    wait_done,
    wait_found,
    watch_until_gone,
)
from src.runner import RunOutcome, TestContext, TestDef


def _fail_early(cps: list, note: str, result: str = "ERROR") -> RunOutcome:
    return RunOutcome(result, cps, notes=note)  # type: ignore[arg-type]


def _outcome(w: Watch, cps: list, extra: dict) -> RunOutcome:
    verdict = deletion_verdict(w.gone_at)
    notes = ""
    if verdict == "SLOW":
        notes = f"gone at {w.gone_at:g}s"
    elif verdict == "FAIL":
        last = next((c for c in reversed(w.checkpoints) if not c.get("confirm")), {})
        notes = f"still present at {last.get('t')}s via {last.get('surfaces')}"
    if w.reappeared:
        notes = (notes + "; " if notes else "") + "content reappeared after a first absence"
    return RunOutcome(verdict, cps + w.checkpoints, time_to_consistency_s=w.gone_at, notes=notes, extra=extra)


def _prepare(ctx: TestContext, tag: str, content: str, query: str, markers: list[str], *, opts: AddOptions | None = None):
    """Add, wait for done, wait until the query finds the content. Returns (scope, doc_id, cps, error_outcome)."""
    p, clock = ctx.provider, ctx.clock
    scope = scope_id(f"memtrust_{tag}")
    ctx.track(scope)
    added = p.add(scope, content, opts)
    cps: list = [{"step": "add", "http": added.http_status, "id": added.doc_id}]
    if not added.doc_id:
        return scope, "", cps, _fail_early(cps, f"add returned no id (HTTP {added.http_status})")
    ready = wait_done(p, scope, added.doc_id, clock)
    state = ready.value.status if ready.value else "missing"
    cps.append({"step": "done", "elapsed_s": ready.elapsed_s, "status": state})
    if state != "done":
        return scope, added.doc_id, cps, _fail_early(cps, f"document never reached done (last status: {state})")
    found = wait_found(p, scope, query, markers, clock)
    cps.append({"step": "searchable_before_delete", "elapsed_s": found.elapsed_s, "found": found.ok})
    if not found.ok:
        return scope, added.doc_id, cps, _fail_early(cps, "content not retrievable before delete; deletion cannot be tested")
    return scope, added.doc_id, cps, None


def _delete_then_watch(ctx: TestContext, scope: str, doc_id: str, query: str, markers: list[str], cps: list, *, profile: bool = False, extra: dict | None = None):
    p = ctx.provider
    deleted = p.delete(scope, [doc_id])
    cps.append({"step": "delete", "http": deleted.http_status, "count": deleted.count, "errors": deleted.errors})
    if deleted.count != 1 or deleted.errors:
        return _fail_early(cps, f"delete not accepted: count={deleted.count} errors={deleted.errors}")
    w = watch_until_gone(lambda: present_surfaces(p, scope, query, markers, profile=profile), ctx.clock)
    return _outcome(w, cps, extra or {})


# --- DEL-01 ---------------------------------------------------------------------------------


def del_01(ctx: TestContext) -> RunOutcome:
    """Add doc with canary, wait until searchable, delete, search by exact canary."""
    c = canary("DEL")
    content = f"Field note: the maintenance code for the pump house is {c}. Keep it with the keys."
    scope, doc_id, cps, err = _prepare(ctx, "del01", content, c, [c])
    if err:
        return err
    return _delete_then_watch(ctx, scope, doc_id, c, [c], cps, extra={"canary": c, "query": c})


# --- DEL-02 ---------------------------------------------------------------------------------


def del_02(ctx: TestContext) -> RunOutcome:
    """Same, but the query is a paraphrase that never mentions the canary or the unique place name."""
    c = canary("DEL")
    place = f"Quenmoor{c[-6:]}"
    content = f"The yearly lantern festival in the village of {place} is organised by Marisol Vance and starts at dusk. Reference {c}."
    paraphrase = "Who runs the annual lights celebration in that village and when does it begin?"
    markers = [c, place]
    scope, doc_id, cps, err = _prepare(ctx, "del02", content, paraphrase, markers)
    if err:
        return err
    return _delete_then_watch(ctx, scope, doc_id, paraphrase, markers, cps, extra={"canary": c, "place": place, "query": paraphrase})


# --- DEL-03 ---------------------------------------------------------------------------------


def del_03(ctx: TestContext) -> RunOutcome:
    """Delete a source doc that produced derived memories. Docs: derived memories are forgotten with it."""
    p, clock = ctx.provider, ctx.clock
    if not p.capabilities().memories_surface:
        return RunOutcome("SKIPPED", notes="no memories surface on this provider")
    token = canary("DEL")
    content = f"Priya's pet iguana is named {token}. Priya adopted the iguana last spring and feeds it every morning."
    query = "What is the name of Priya's pet iguana?"
    scope = scope_id("memtrust_del03")
    ctx.track(scope)
    added = p.add(scope, content, AddOptions(dreaming="instant"))
    cps: list = [{"step": "add", "http": added.http_status, "id": added.doc_id}]
    if not added.doc_id:
        return _fail_early(cps, f"add returned no id (HTTP {added.http_status})")
    ready = wait_done(p, scope, added.doc_id, clock, timeout_s=300, dreaming=True)
    cps.append({"step": "done_and_dreamed", "elapsed_s": ready.elapsed_s, "status": ready.value.status if ready.value else "missing", "dreaming": ready.value.dreaming_status if ready.value else None})
    if not ready.ok or not ready.value or ready.value.status != "done":
        return _fail_early(cps, "document did not finish processing within 300s")

    mem = wait_found(p, scope, query, [token], clock, mode="memories", timeout_s=120, interval_s=5)
    cps.append({"step": "memory_before_delete", "elapsed_s": mem.elapsed_s, "found": mem.ok})
    if not mem.ok:
        # No derived memory carries the token, so persistence could not be detected. Do not report a pass.
        return RunOutcome("SKIPPED", cps, notes="no derived memory containing the token surfaced; DEL-03 not applicable for this run")

    profile_before = p.profile(scope).entries if p.capabilities().profiles else []
    cps.append({"step": "profile_before", "token_in_profile": any(token in e for e in profile_before)})

    out = _delete_then_watch(ctx, scope, added.doc_id, query, [token], cps, profile=True, extra={"token": token, "query": query})

    # Evidence only (amendment A1): soft-deleted memories are expected to be visible with include_forgotten.
    try:
        forgotten = p.search(scope, query, SearchOptions(mode="memories", include_forgotten=True)).hits
        out.extra["forgotten_visible_with_flag"] = any(token in h.text for h in forgotten)
    except Exception as e:  # evidence is best-effort
        out.extra["forgotten_visible_with_flag"] = f"error: {e}"
    return out


# --- DEL-04 ---------------------------------------------------------------------------------


def del_04(ctx: TestContext) -> RunOutcome:
    """Delete while the doc is still processing. Docs: it is rejected ('Document is still processing')."""
    p, clock = ctx.provider, ctx.clock
    c = canary("DEL")
    content = f"Race note: the gate combination for the east yard is {c}."
    scope = scope_id("memtrust_del04")
    ctx.track(scope)
    added = p.add(scope, content)
    cps: list = [{"step": "add", "http": added.http_status, "id": added.doc_id}]
    if not added.doc_id:
        return _fail_early(cps, f"add returned no id (HTTP {added.http_status})")

    before = p.status(scope, added.doc_id)
    cps.append({"step": "status_before_delete", "status": before.status if before else None})
    if before is None or before.status in ("done", "failed"):
        return RunOutcome("SKIPPED", cps, notes=f"document was already {before.status if before else 'missing'} at delete time; no race to test")

    deleted = p.delete(scope, [added.doc_id])
    cps.append({"step": "delete_while_processing", "http": deleted.http_status, "count": deleted.count, "errors": deleted.errors})

    if deleted.count == 0 and deleted.errors:
        if not any("processing" in str(e.get("error", "")).lower() for e in deleted.errors):
            return _fail_early(cps, f"delete rejected for an unexpected reason: {deleted.errors}")
        # Documented behaviour. The doc must be unharmed: it finishes and is retrievable.
        ready = wait_done(p, scope, added.doc_id, clock)
        state = ready.value.status if ready.value else "missing"
        cps.append({"step": "done_after_rejected_delete", "elapsed_s": ready.elapsed_s, "status": state})
        if state != "done":
            return RunOutcome("FAIL", cps, notes=f"rejected delete left the document in state {state!r}; it should have completed", extra={"canary": c})
        found = wait_found(p, scope, c, [c], clock)
        cps.append({"step": "searchable_after_rejected_delete", "elapsed_s": found.elapsed_s, "found": found.ok})
        if not found.ok:
            return RunOutcome("FAIL", cps, notes="delete was rejected but the document never became searchable", extra={"canary": c})
        return RunOutcome("PASS", cps, notes="rejected as documented; document completed intact", extra={"canary": c, "outcome": "rejected"})

    if deleted.count == 1 and not deleted.errors:
        # Accepted although the docs say it is rejected. The PRD assertion applies: it must never become searchable.
        ready = wait_done(p, scope, added.doc_id, clock, timeout_s=60)
        w = watch_until_gone(lambda: present_surfaces(p, scope, c, [c]), clock, schedule=(0, 5, 30, 120))
        present_at_end = bool(w.checkpoints[-1]["canaryPresent"]) or w.reappeared
        cps.extend(w.checkpoints)
        if w.gone_at is None or present_at_end:
            return RunOutcome("FAIL", cps, notes="deleted while processing, then became searchable (resurrected)", extra={"canary": c, "outcome": "accepted_then_resurrected"})
        return RunOutcome("PASS", cps, notes="accepted although the docs say it is rejected; document never became searchable", extra={"canary": c, "outcome": "accepted_never_searchable"})

    return _fail_early(cps, f"unexpected delete response: count={deleted.count} errors={deleted.errors}")


# --- DEL-05 ---------------------------------------------------------------------------------


def del_05(ctx: TestContext) -> RunOutcome:
    """Re-add identical content after deletion: searchable again, no ghost of the old state.

    Two variants per run: the same caller id in the same scope, and a new id in a fresh scope."""
    p, clock = ctx.provider, ctx.clock
    c = canary("DEL")
    content = f"Archive note: the vault reference number is {c}."
    caller_id = f"memtrust-del05-{c[-8:].lower()}"
    cps: list = []
    extra: dict = {"canary": c, "caller_id": caller_id}

    scope, doc_id, pre, err = _prepare(ctx, "del05a", content, c, [c], opts=AddOptions(id=caller_id))
    cps += pre
    if err:
        return err

    deleted = p.delete(scope, [doc_id])
    cps.append({"step": "delete", "count": deleted.count, "errors": deleted.errors})
    if deleted.count != 1 or deleted.errors:
        return _fail_early(cps, f"delete not accepted: count={deleted.count} errors={deleted.errors}")
    w = watch_until_gone(lambda: present_surfaces(p, scope, c, [c]), clock)
    cps += w.checkpoints
    if deletion_verdict(w.gone_at) == "FAIL":
        return RunOutcome("FAIL", cps, notes="original content never went away, so re-add could not be tested", extra=extra)

    # Variant A: same caller id, same scope.
    again = p.add(scope, content, AddOptions(id=caller_id))
    cps.append({"step": "readd_same_id", "http": again.http_status, "id": again.doc_id})
    if not again.doc_id:
        return _fail_early(cps, f"re-add returned no id (HTTP {again.http_status})")
    ready = wait_done(p, scope, again.doc_id, clock)
    if not ready.value or ready.value.status != "done":
        return RunOutcome("FAIL", cps, notes=f"re-added document did not finish (status {ready.value.status if ready.value else 'missing'})", extra=extra)
    found = wait_found(p, scope, c, [c], clock, mode="chunks")
    cps.append({"step": "searchable_after_readd_same_id", "elapsed_s": found.elapsed_s, "found": found.ok})
    if not found.ok:
        return RunOutcome("FAIL", cps, notes="re-added identical content is not searchable again", extra=extra)
    copies = [h for h in p.search(scope, c, SearchOptions(mode="chunks")).hits if c in h.text]
    extra["chunk_copies_after_readd"] = len(copies)
    cps.append({"step": "chunk_copies", "n": len(copies)})
    if len(copies) != 1:
        return RunOutcome("FAIL", cps, notes=f"expected 1 chunk with the canary after re-add, found {len(copies)} (ghost of the old state)", extra=extra)

    # Variant B: new id, fresh scope.
    scope_b, doc_b, pre_b, err_b = _prepare(ctx, "del05b", content, c, [c])
    cps += [dict(s, variant="B") for s in pre_b]
    if err_b:
        return RunOutcome("FAIL", cps, notes=f"identical content under a new id in a fresh scope failed: {err_b.notes}", extra=extra)

    return RunOutcome("PASS", cps, time_to_consistency_s=w.gone_at, notes="" if w.gone_at is not None and w.gone_at <= 120 else f"original gone at {w.gone_at:g}s", extra=extra)


DEL_01 = TestDef("DEL-01", "DEL", "Delete doc, exact canary search", del_01)
DEL_02 = TestDef("DEL-02", "DEL", "Delete doc, paraphrase search", del_02)
DEL_03 = TestDef("DEL-03", "DEL", "Delete source doc, derived memories and profile", del_03)
DEL_04 = TestDef("DEL-04", "DEL", "Delete while processing", del_04)
DEL_05 = TestDef("DEL-05", "DEL", "Re-add identical content after delete", del_05)

TESTS = [DEL_01, DEL_02, DEL_03, DEL_04, DEL_05]


@pytest.mark.parametrize("test", TESTS, ids=lambda t: t.id)
def test_del(test, check):
    check(test)
