"""COR: corrections and knowledge updates. Rules: docs/decisions.md D8 (pre-registered at tag `prereg-cor`).

"Current" means returned as a memory by a normal retrieval surface (memory search, memory hits in hybrid, profile) and
not marked isLatest=false. Raw chunks are evidence only: a stale document chunk is never reported as a bug (D3).
Every test first proves each earlier fact existed as a memory, so "the old fact is gone" cannot be vacuous.
"""

from __future__ import annotations

import os

import pytest

from src.adapter import SearchOptions
from src.corrections import PAST_CUE, chunk_evidence, current_hits, judge_update, seed_chain, settle, verdict_from
from src.runner import RunOutcome, TestContext, TestDef

DREAMING = os.environ.get("MEMTRUST_COR_DREAMING", "instant")  # "dynamic" for the single default-mode timing sample


def _seed(ctx, label, n, make_docs, query, cps):
    return seed_chain(ctx, label, n, make_docs, query, cps, dreaming=DREAMING)


def _update_test(ctx: TestContext, label: str, query: str, docs, *, rank_tolerant: bool = False) -> RunOutcome:
    """Shared body: docs[i] states a fact, the last one is the correction. The first n-1 tokens are old, the last is new."""
    p = ctx.provider
    cps: list = []
    scope, toks, err = _seed(ctx, label, len(docs), lambda t: [(d(t[i]), [t[i]]) for i, d in enumerate(docs)], query, cps)
    if err:
        return err
    new, old = toks[-1], toks[:-1]
    probes = settle(lambda: judge_update(p, scope, query, new, old, rank_tolerant=rank_tolerant), ctx.clock)
    return verdict_from(probes, cps, {"tokens": {"old": old, "new": new}, "dreaming": DREAMING}, fail_note="stale or missing fact")


# --- COR-01 ---------------------------------------------------------------------------------


def cor_01(ctx: TestContext) -> RunOutcome:
    """Explicit move: 'lives in A', later 'moved, now lives in B'."""
    return _update_test(
        ctx, "cor01", "Which city does Ravi live in?",
        [lambda t: f"Ravi lives in the city of Zorvania-{t}.", lambda t: f"Ravi moved. Ravi now lives in the city of Quentaria-{t}."],
    )


# --- COR-02 ---------------------------------------------------------------------------------


def cor_02(ctx: TestContext) -> RunOutcome:
    """Implicit update: no 'moved' or 'now' cue, just a different employer later. Rank may stand in for supersession."""
    return _update_test(
        ctx, "cor02", "Which company does Priya work at?",
        [lambda t: f"Priya works as a data engineer at the company Ardenmoor-{t}.", lambda t: f"Priya is a data engineer at the company Belvandria-{t}, and the team there is friendly."],
        rank_tolerant=True,
    )


# --- COR-03 ---------------------------------------------------------------------------------


def cor_03(ctx: TestContext) -> RunOutcome:
    """'Used to X, now Y' in a single document: the old value must never be presented as current."""
    p = ctx.provider
    query = "Where does Meera live?"
    cps: list = []
    scope, toks, err = _seed(
        ctx, "cor03", 2, lambda t: [(f"Meera used to live in Alpheria-{t[0]}, but now lives in Brenmoor-{t[1]}.", [t[1]])], query, cps
    )
    if err:
        return err
    old, new = toks

    def probe() -> dict:
        now = current_hits(p, scope, query, [new, old])
        new_current = any(h["token"] == new and h["surface"] == "search:memories" for h in now)
        presented_as_current = [h for h in now if h["token"] == old and new not in h["text"] and not PAST_CUE.search(h["text"])]
        history_kept = any(h["token"] == old for h in now)
        problems = []
        if not new_current:
            problems.append("the new value is not current in memory search")
        problems += [f"old value presented as current via {h['surface']}: {h['text']!r}" for h in presented_as_current]
        return {
            "ok": not problems,
            "problem": "; ".join(problems),
            "history_kept_as_memory": history_kept,
            "old_texts": [h["text"] for h in now if h["token"] == old],
            "chunks": chunk_evidence(p, scope, query, [new, old]),
        }

    probes = settle(probe, ctx.clock)
    out = verdict_from(probes, cps, {"tokens": {"old": old, "new": new}, "dreaming": DREAMING}, fail_note="old value presented as current")
    if out.result == "PASS":
        kept = probes[-1]["history_kept_as_memory"]
        out.notes = (out.notes + "; " if out.notes else "") + ("history kept as a memory with past framing" if kept else "old value not kept as a memory (history not preserved)")
    return out


# --- COR-04 ---------------------------------------------------------------------------------


def cor_04(ctx: TestContext) -> RunOutcome:
    """Chain of three updates to the same fact; the latest must win and neither earlier value may be current."""
    return _update_test(
        ctx, "cor04", "What is the project codename Sana is using?",
        [
            lambda t: f"Sana's project codename is Kelvaria-{t}.",
            lambda t: f"Sana's project codename changed; the codename is now Drumholt-{t}.",
            lambda t: f"Sana's project codename changed again; the codename is now Wexmoor-{t}.",
        ],
    )


# --- COR-05 ---------------------------------------------------------------------------------


def cor_05(ctx: TestContext) -> RunOutcome:
    """Retraction by text. Characterization: the docs only describe retraction through explicit forget calls, so a
    retained fact is DOCUMENTED rather than FAIL (D8)."""
    p = ctx.provider
    query = "What is the combination of Dev's locker?"
    cps: list = []
    scope, toks, err = _seed(
        ctx, "cor05", 1,
        lambda t: [
            (f"Dev keeps a gym locker and the lock combination is Orvane-{t[0]}.", [t[0]]),
            ("Dev asked: please forget what I told you earlier about my locker lock, and disregard it entirely.", []),
        ],
        query, cps,
    )
    if err:
        return err
    (old,) = toks

    def probe() -> dict:
        still = current_hits(p, scope, query, [old])
        return {
            "ok": not still,
            "problem": "; ".join(f"{h['token']} still current via {h['surface']}" for h in still),
            "chunks": chunk_evidence(p, scope, query, [old]),
        }

    probes = settle(probe, ctx.clock)
    out = verdict_from(probes, cps, {"tokens": {"retracted": old}, "dreaming": DREAMING}, fail_note="retracted fact still current", bad_result="DOCUMENTED")
    if out.result == "DOCUMENTED":
        out.notes = "retraction by text was not honored (docs: retraction only via explicit forget calls): " + out.notes
    return out


# --- COR-06 ---------------------------------------------------------------------------------


def cor_06(ctx: TestContext) -> RunOutcome:
    """Explicit forget call: documented as excluded from search results. Chunks of the source document remain by design."""
    p = ctx.provider
    forget = getattr(p, "forget", None)
    if forget is None:
        return RunOutcome("SKIPPED", notes="provider has no explicit forget call")
    query = "What is the number on Lena's building badge?"
    cps: list = []
    scope, toks, err = _seed(ctx, "cor06", 1, lambda t: [(f"Lena holds a building badge and the badge number is Tavrenn-{t[0]}.", [t[0]])], query, cps)
    if err:
        return err
    (tok,) = toks
    ids = [h.id for h in p.search(scope, query, SearchOptions(mode="memories")).hits if h.kind == "memory" and tok in h.text]
    if not ids:
        return RunOutcome("INCONCLUSIVE", cps, notes="the memory vanished between seeding and the forget call; cannot forget what cannot be found")
    res = forget(scope, ids)
    cps.append({"step": "forget", "ids": ids, "http": res.http_status, "count": res.count, "errors": res.errors})
    if res.http_status >= 400 or res.count == 0:
        return RunOutcome("INCONCLUSIVE", cps, notes=f"forget call was not accepted (HTTP {res.http_status}, count {res.count}, errors {res.errors}); inspect before judging")

    def probe() -> dict:
        still = current_hits(p, scope, query, [tok])
        return {"ok": not still, "problem": "; ".join(f"still current via {h['surface']}" for h in still), "chunks": chunk_evidence(p, scope, query, [tok])}

    probes = settle(probe, ctx.clock)
    flagged = [h for h in p.search(scope, query, SearchOptions(mode="memories", include_forgotten=True)).hits if tok in h.text]
    cps.append({"step": "evidence_include_forgotten", "returned_with_flag": bool(flagged)})
    return verdict_from(probes, cps, {"token": tok, "forget_count": res.count, "returned_with_include_forgotten": bool(flagged)}, fail_note="forgotten memory still returned")


COR_01 = TestDef("COR-01", "COR", "Explicit move", cor_01)
COR_02 = TestDef("COR-02", "COR", "Implicit update (no cue)", cor_02)
COR_03 = TestDef("COR-03", "COR", "Used to X, now Y", cor_03)
COR_04 = TestDef("COR-04", "COR", "Chain of three updates", cor_04)
COR_05 = TestDef("COR-05", "COR", "Retraction by text (characterization)", cor_05)
COR_06 = TestDef("COR-06", "COR", "Explicit forget call", cor_06)

TESTS = [COR_01, COR_02, COR_03, COR_04, COR_05, COR_06]


@pytest.mark.parametrize("test", TESTS, ids=lambda t: t.id)
def test_cor(test, check):
    check(test)
