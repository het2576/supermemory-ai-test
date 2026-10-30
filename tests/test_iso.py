"""ISO: tenant isolation. Rules: docs/guarantees-matrix.md section 2.2 and docs/decisions.md D2.

Zero tolerance: foreign content from any normal retrieval surface, at any probe, in any run, is a FAIL
candidate (the report states n/3). Every test first proves each tenant can retrieve its OWN content, so
"nothing leaked" cannot be an artefact of nothing being searchable. ISO-02 is characterization only.
"""

from __future__ import annotations

import uuid

import pytest

from src.adapter import AddOptions
from src.assertions import canary, scope_id
from src.deletion import present_surfaces, wait_done, wait_found
from src.runner import RunOutcome, TestContext, TestDef
from src.wait import at_checkpoints

PROBES_S = (0, 5, 30)


def _err(cps: list, note: str) -> RunOutcome:
    return RunOutcome("ERROR", cps, notes=note)


def _seed(ctx: TestContext, scope: str, content: str, query: str, own: list[str], cps: list, label: str, *, dreaming: bool = False):
    """Add content to scope and wait until the scope's own query finds it. Returns an error outcome or None."""
    p, clock = ctx.provider, ctx.clock
    added = p.add(scope, content, AddOptions(dreaming="instant") if dreaming else None)
    cps.append({"step": f"add_{label}", "scope": scope, "http": added.http_status, "id": added.doc_id})
    if not added.doc_id:
        return _err(cps, f"add for {label} returned no id (HTTP {added.http_status})")
    ready = wait_done(p, scope, added.doc_id, clock, timeout_s=300 if dreaming else 120, dreaming=dreaming)
    state = ready.value.status if ready.value else "missing"
    if state != "done":
        return _err(cps, f"{label} document never reached done (last status: {state})")
    found = wait_found(p, scope, query, own, clock)
    cps.append({"step": f"own_content_retrievable_{label}", "elapsed_s": found.elapsed_s, "found": found.ok})
    if not found.ok:
        return _err(cps, f"{label} cannot retrieve its own content; isolation cannot be tested")
    return None


def _verdict(cps: list, probes, extra: dict, fail_label: str = "foreign content returned") -> RunOutcome:
    leaks = [(c.t, leak) for c in probes for leak in c.value["leaks"]]
    cps.extend({"t": c.t, **c.value} for c in probes)
    if leaks:
        t, first = leaks[0]
        return RunOutcome("FAIL", cps, notes=f"{fail_label}: {first} at t={t:g}s ({len(leaks)} leak(s) over {len(probes)} probes)", extra=extra)
    return RunOutcome("PASS", cps, notes="", extra=extra)


# --- ISO-01 ---------------------------------------------------------------------------------


def iso_01(ctx: TestContext) -> RunOutcome:
    """A and B each add a unique canary. Search as B for A's canary (and as A for B's)."""
    p = ctx.provider
    sa, sb = scope_id("memtrust_iso01a"), scope_id("memtrust_iso01b")
    ctx.track(sa), ctx.track(sb)
    ca, cb = canary("ISO"), canary("ISO")
    semantic = "What is the account recovery phrase?"
    cps: list = []
    for label, scope, c in (("A", sa, ca), ("B", sb, cb)):
        err = _seed(ctx, scope, f"Tenant {label} internal memo: the account recovery phrase is {c}.", c, [c], cps, label)
        if err:
            return err

    def probe():
        leaks = []
        for viewer, owner, foreign in (("B", "A", ca), ("A", "B", cb)):
            scope = sb if viewer == "B" else sa
            for qname, q in (("exact", foreign), ("semantic", semantic)):
                for s in present_surfaces(p, scope, q, [foreign], profile=(qname == "exact")):
                    leaks.append(f"{viewer} saw {owner}'s canary via {s} ({qname} query)")
        return {"leaks": leaks}

    return _verdict(cps, at_checkpoints(probe, PROBES_S, clock=ctx.clock), {"canaries": {"A": ca, "B": cb}})


# --- ISO-02 ---------------------------------------------------------------------------------


def iso_02(ctx: TestContext) -> RunOutcome:
    """No scope specified. v5 requires a namespace in the URL, so this uses the legacy route where containerTag is optional.

    Characterization only (D2): DOCUMENTED if the unscoped call spans namespaces (the legacy docs call containerTag
    optional, "to filter"), PASS if it is rejected or returns nothing foreign."""
    p = ctx.provider
    search_unscoped = getattr(p, "search_unscoped", None)
    if search_unscoped is None:
        return RunOutcome("SKIPPED", notes="provider has no unscoped search route")
    sa, sb = scope_id("memtrust_iso02a"), scope_id("memtrust_iso02b")
    ctx.track(sa), ctx.track(sb)
    ca, cb = canary("ISO"), canary("ISO")
    cps: list = []
    for label, scope, c in (("A", sa, ca), ("B", sb, cb)):
        err = _seed(ctx, scope, f"Tenant {label} shipping note: the container seal number is {c}.", c, [c], cps, label)
        if err:
            return err

    seen = {"A": False, "B": False}
    statuses = []
    for _ in range(2):  # repeat once to see whether the answer is stable
        for label, c in (("A", ca), ("B", cb)):
            r = search_unscoped(c)
            statuses.append(r.http_status)
            seen[label] = seen[label] or any(c in h.text for h in r.hits)
    cps.append({"step": "unscoped_search", "http_statuses": statuses, "saw_A": seen["A"], "saw_B": seen["B"]})
    extra = {"canaries": {"A": ca, "B": cb}, "statuses": statuses, "seen": seen}

    if all(s >= 400 for s in statuses):
        return RunOutcome("PASS", cps, notes=f"unscoped search rejected (HTTP {sorted(set(statuses))})", extra=extra)
    if seen["A"] or seen["B"]:
        both = seen["A"] and seen["B"]
        return RunOutcome("DOCUMENTED", cps, notes=f"unscoped legacy search spans namespaces (saw {'both tenants' if both else 'one tenant'}); containerTag is documented as optional", extra=extra)

    # Accepted but returned neither canary. That proves nothing unless the same route CAN see this data when scoped.
    control = {label: any(c in h.text for h in search_unscoped(c, container_tag=scope).hits) for label, scope, c in (("A", sa, ca), ("B", sb, cb))}
    cps.append({"step": "positive_control_scoped_legacy_search", "found": control})
    extra["control"] = control
    if all(control.values()):
        return RunOutcome("PASS", cps, notes="unscoped legacy search accepted but returned nothing, while the same route scoped to each tenant found its canary: unscoped is not org-wide (it must default elsewhere)", extra=extra)
    return RunOutcome("INCONCLUSIVE", cps, notes=f"unscoped search returned nothing and the scoped control did not find the data either ({control}); the legacy route may not see v5 data, so unscoped behavior is unknown", extra=extra)


# --- ISO-03 ---------------------------------------------------------------------------------


def iso_03(ctx: TestContext) -> RunOutcome:
    """Near-duplicate content in two tenants, differing only in the canary. Neither may see the other's."""
    p = ctx.provider
    sa, sb = scope_id("memtrust_iso03a"), scope_id("memtrust_iso03b")
    ctx.track(sa), ctx.track(sb)
    ca, cb = canary("ISO"), canary("ISO")
    query = "What is the warehouse alarm code and when does the night guard start?"
    cps: list = []
    for label, scope, c in (("A", sa, ca), ("B", sb, cb)):
        err = _seed(ctx, scope, f"The warehouse alarm code is {c} and the night guard starts at nine.", query, [c], cps, label)
        if err:
            return err

    def probe():
        leaks, own = [], {}
        for viewer, scope, mine, foreign in (("A", sa, ca, cb), ("B", sb, cb, ca)):
            own[viewer] = bool(present_surfaces(p, scope, query, [mine], modes=("chunks",)))
            for s in present_surfaces(p, scope, query, [foreign]):
                leaks.append(f"{viewer} saw the other tenant's near-duplicate via {s}")
        return {"leaks": leaks, "own_present": own}

    return _verdict(cps, at_checkpoints(probe, PROBES_S, clock=ctx.clock), {"canaries": {"A": ca, "B": cb}})


# --- ISO-04 ---------------------------------------------------------------------------------


def iso_04(ctx: TestContext) -> RunOutcome:
    """Look-alike scope IDs (valid ones must stay strictly separate) and invalid IDs (must be rejected, not normalized)."""
    p = ctx.provider
    u = uuid.uuid4().hex[:8]
    valid = {
        "base": f"memtrust_{u}_1",
        "ten": f"memtrust_{u}_10",
        "colon": f"memtrust_{u}_1:x",
        "upper": f"MEMTRUST_{u}_1",  # case variant of base
        "hyphen": f"memtrust_{u}-1",
        "trailing_underscore": f"memtrust_{u}_1_",
    }
    canaries = {k: canary("ISO") for k in valid}
    query = "What is the reference code on file?"
    cps: list = []
    for k, scope in valid.items():
        ctx.track(scope)
        err = _seed(ctx, scope, f"The reference code on file is {canaries[k]}.", query, [canaries[k]], cps, k)
        if err:
            return err

    invalid = {"trailing_space": f"memtrust_{u}_1 ", "slash": f"memtrust_{u}/1", "at": f"memtrust_{u}@1"}
    inv_canaries = {k: canary("ISO") for k in invalid}
    attempts = {}
    for k, scope in invalid.items():
        try:
            r = p.add(scope, f"The reference code on file is {inv_canaries[k]}.")
            attempts[k] = {"http": r.http_status, "accepted": bool(r.doc_id)}
            if r.doc_id:
                ctx.track(scope)
        except Exception as e:  # rejected client-side by the SDK or transport
            attempts[k] = {"http": None, "accepted": False, "client_error": f"{type(e).__name__}: {e}"[:200]}
    cps.append({"step": "invalid_scope_attempts", "attempts": attempts})

    def probe():
        leaks = []
        all_foreign = {k: c for k, c in canaries.items()}
        for k, scope in valid.items():
            others = [c for kk, c in all_foreign.items() if kk != k] + list(inv_canaries.values())
            for s in present_surfaces(p, scope, query, others):
                leaks.append(f"scope {scope!r} returned another scope's content via {s}")
        return {"leaks": leaks}

    out = _verdict(cps, at_checkpoints(probe, (0, 30), clock=ctx.clock), {"valid": valid, "invalid": invalid, "attempts": attempts})
    accepted = [k for k, a in attempts.items() if a["accepted"]]
    if out.result == "PASS" and accepted:
        out.notes = f"invalid IDs accepted despite the documented pattern: {accepted}; none collided with a valid scope"
    elif out.result == "PASS":
        out.notes = "invalid IDs rejected"
    return out


# --- ISO-05 ---------------------------------------------------------------------------------


MAX_SEED_ATTEMPTS = 3  # amendment A2: the memory extractor sometimes alters the token; retry with a fresh one


def _seed_with_memory(ctx: TestContext, label: str, sentence, query: str, cps: list):
    """Seed one tenant so a derived memory AND a profile entry carry its token. Retries with a fresh scope and
    token when extraction alters it. Returns (scope, token, None) or (None, None, skip_or_error_outcome)."""
    p = ctx.provider
    last_reason = ""
    for attempt in range(1, MAX_SEED_ATTEMPTS + 1):
        scope, token = scope_id(f"memtrust_iso05{label.lower()}"), canary("ISO")
        ctx.track(scope)
        err = _seed(ctx, scope, sentence(token), query, [token], cps, f"{label}{attempt}", dreaming=True)
        if err:
            return None, None, err
        mem = wait_found(p, scope, query, [token], ctx.clock, mode="memories", timeout_s=120, interval_s=5)
        cps.append({"step": f"memory_{label}", "attempt": attempt, "found": mem.ok, "elapsed_s": mem.elapsed_s})
        if not mem.ok:
            last_reason = f"no derived memory with {label}'s exact token surfaced"
            continue
        if not any(token in e for e in p.profile(scope).entries):
            cps.append({"step": f"profile_{label}", "attempt": attempt, "token_in_profile": False})
            last_reason = f"{label}'s own profile does not contain {label}'s exact token"
            continue
        return scope, token, None
    return None, None, RunOutcome("SKIPPED", cps, notes=f"{last_reason} after {MAX_SEED_ATTEMPTS} attempts; profile bleed cannot be detected")


def iso_05(ctx: TestContext) -> RunOutcome:
    """Profile and derived-memory bleed: does A's profile or memory search contain B's facts?"""
    p = ctx.provider
    if not p.capabilities().profiles:
        return RunOutcome("SKIPPED", notes="provider has no profiles")
    query = "Where does this person work and what do they prefer?"
    cps: list = []
    sa, ca, err = _seed_with_memory(ctx, "A", lambda t: f"Anika works at the firm {t}. Anika prefers window seats on every flight.", query, cps)
    if err:
        return err
    sb, cb, err = _seed_with_memory(ctx, "B", lambda t: f"Bruno works at the firm {t}. Bruno prefers aisle seats on every flight.", query, cps)
    if err:
        return err

    def probe():
        leaks = []
        for viewer, scope, foreign in (("A", sa, cb), ("B", sb, ca)):
            for s in present_surfaces(p, scope, query, [foreign], modes=("memories", "hybrid"), profile=True):
                leaks.append(f"{viewer} saw the other tenant's fact via {s}")
        return {"leaks": leaks}

    return _verdict(cps, at_checkpoints(probe, PROBES_S, clock=ctx.clock), {"canaries": {"A": ca, "B": cb}})


ISO_01 = TestDef("ISO-01", "ISO", "Cross-tenant search by canary", iso_01)
ISO_02 = TestDef("ISO-02", "ISO", "No scope specified (characterization)", iso_02)
ISO_03 = TestDef("ISO-03", "ISO", "Near-duplicate content across tenants", iso_03)
ISO_04 = TestDef("ISO-04", "ISO", "Look-alike and invalid scope IDs", iso_04)
ISO_05 = TestDef("ISO-05", "ISO", "Profile and memory bleed", iso_05)

TESTS = [ISO_01, ISO_02, ISO_03, ISO_04, ISO_05]


@pytest.mark.parametrize("test", TESTS, ids=lambda t: t.id)
def test_iso(test, check):
    check(test)
