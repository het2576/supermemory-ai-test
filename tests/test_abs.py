"""ABS: abstention. Protocol: docs/decisions.md D10 (pre-registered at tag `prereg-abs`).

Mechanical only: what similarity scores the API returns for questions it can and cannot answer, and what the documented
`threshold` parameter does about it. Every test reports DOCUMENTED; the raw rows (top score and top text per query)
are in each run's evidence file. Whether a returned item could mislead a model is a labeled qualitative appendix.
"""

from __future__ import annotations

import pytest

from src.abstention import class_summary, separation
from src.adapter import AddOptions, SearchOptions
from src.assertions import scope_id
from src.deletion import wait_done
from src.latency import percentile
from src.runner import RunOutcome, TestContext, TestDef

# (stored sentence, paraphrased question, marker word that proves the right fact came back)
FACTS = [
    ("My dentist is Dr. Valdemar Okonkwo.", "Who looks after my teeth?", "Okonkwo"),
    ("I adopted a greyhound named Pistachio.", "What is my dog called?", "Pistachio"),
    ("My daughter attends Larkspur Academy.", "Which school does my child go to?", "Larkspur"),
    ("I drive a teal 2014 Subaru Forester.", "What vehicle do I own?", "Forester"),
    ("I am allergic to cashews.", "Which food should I avoid?", "cashews"),
    ("My sister lives in Tromso.", "In which city does my sibling live?", "Tromso"),
    ("I play the cello in the Marlowe Quartet.", "Which musical instrument do I play?", "cello"),
    ("My favorite tea is lapsang souchong.", "What do I like to drink in the afternoon?", "lapsang"),
    ("I run the Halvorsen Bridge loop every Sunday.", "Where do I jog at the weekend?", "Halvorsen"),
    ("My landlord is Mrs. Ekaterina Brandt.", "Who do I pay rent to?", "Brandt"),
    ("I booked a trip to Oaxaca for March.", "Where am I going on holiday?", "Oaxaca"),
    ("My phone plan is with Quillfeather Mobile.", "Which company provides my mobile service?", "Quillfeather"),
    ("I learned to bake sourdough from my grandfather Anselm.", "Who taught me to make bread?", "Anselm"),
    ("My gym membership is at the Ironwood Club.", "Where do I work out?", "Ironwood"),
    ("I keep my bicycle in locker 42B.", "Where is my bike kept?", "42B"),
    ("My favorite film is The Silent Lighthouse.", "Which movie do I love most?", "Lighthouse"),
    ("I work night shifts at Coral Bay Hospital.", "At what place am I employed?", "Coral"),
    ("My book club meets on the second Thursday.", "On which day does my reading group gather?", "Thursday"),
    ("I am learning Icelandic with the Fjord app.", "Which foreign language am I studying?", "Icelandic"),
    ("My emergency contact is my cousin Teodora.", "Who should be called in an emergency?", "Teodora"),
]
ANSWERABLE = [q for _, q, _ in FACTS]
MARKERS = {q: m for _, q, m in FACTS}
NEAR_MISS = [
    "What is my blood type?", "What is my shoe size?", "What is my passport number?", "What is my mother's maiden name?",
    "What is my favorite color?", "Which airline do I prefer?", "What is my cat called?", "Which university did I attend?",
    "What is my yearly salary?", "Who is my accountant?", "What is my wifi password?", "When is my wedding anniversary?",
    "Which bank do I use?", "What is my son's name?", "What is my favorite restaurant?", "Where did I grow up?",
    "What is my shirt size?", "Who is my family doctor?", "Which pharmacy do I use?", "Who is my insurance provider?",
]
OFF_DOMAIN = [
    "What is the capital of Mongolia?", "How does photosynthesis work?", "At what temperature does water boil at sea level?",
    "Who wrote the play Hamlet?", "How do I sort a list in Python?", "How far away is the Moon?",
    "What is the GDP of Brazil?", "How do I tie a tie?", "What is the chemical symbol for gold?", "How many legs does a spider have?",
]
NONSENSE = ["zxqvk blorptangle 7731", "qwfpgj mnbvcx", "ZQ-ABS-0000000000ff", "flumbrix quozzle snarfle", "xxyyzz 9981 wumpa"]
CLASSES = {"answerable": ANSWERABLE, "near_miss": NEAR_MISS, "off_domain": OFF_DOMAIN, "nonsense": NONSENSE}
MODES = ("chunks", "memories", "hybrid")
SWEEP = (None, 0.0, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8)  # None = parameter omitted (documented default 0.3)
MIN_RETRIEVABLE = 18  # D10 precondition: answerable queries that find their fact at threshold 0


def _seed(ctx: TestContext, label: str, cps: list) -> tuple[str | None, RunOutcome | None]:
    """20 facts, one document each, instant dreaming, all processed. Returns (scope, None) or (None, outcome)."""
    p = ctx.provider
    scope = scope_id(f"memtrust_{label}")
    ctx.track(scope)
    ids = []
    for sentence, _, _ in FACTS:
        added = p.add(scope, sentence, AddOptions(dreaming="instant"))
        if not added.doc_id:
            return None, RunOutcome("ERROR", cps, notes=f"seed add returned no id (HTTP {added.http_status})")
        ids.append(added.doc_id)
    pending = 0
    for doc_id in ids:
        ready = wait_done(p, scope, doc_id, ctx.clock, timeout_s=300, dreaming=True)
        if not (ready.value and ready.value.status == "done"):
            pending += 1
    cps.append({"step": "seeded", "documents": len(ids), "not_done": pending})
    if pending:
        return None, RunOutcome("ERROR", cps, notes=f"{pending} of {len(ids)} seed documents never reached done")
    return scope, None


def _query(p, scope: str, q: str, cls: str, mode: str, threshold: float | None) -> dict:
    res = p.search(scope, q, SearchOptions(mode=mode, threshold=threshold))  # type: ignore[arg-type]
    scores = [h.score for h in res.hits if h.score is not None]
    top_hit = max(res.hits, key=lambda h: h.score if h.score is not None else -1, default=None)
    marker = MARKERS.get(q)
    return {
        "q": q, "class": cls, "mode": mode, "threshold": threshold, "http": res.http_status,
        "n": len(res.hits), "top": max(scores) if scores else None,
        "top_kind": top_hit.kind if top_hit else None, "top_text": top_hit.text[:160] if top_hit else None,
        "ids": sorted(h.id for h in res.hits), "hits": [[h.id, h.score] for h in res.hits],
        "correct": bool(marker) and any(marker.lower() in h.text.lower() for h in res.hits),
    }


def _collect(p, scope: str, classes: list[str], modes: tuple[str, ...], thresholds: tuple) -> list[dict]:
    return [_query(p, scope, q, cls, mode, t) for cls in classes for q in CLASSES[cls] for mode in modes for t in thresholds]


def _precondition(rows: list[dict]) -> int:
    return sum(1 for r in rows if r["class"] == "answerable" and r["mode"] == "hybrid" and r["threshold"] == 0.0 and r["correct"])


def _tops(rows: list[dict], cls: str | list[str], mode: str, threshold: float | None) -> list[float | None]:
    want = [cls] if isinstance(cls, str) else cls
    return [r["top"] for r in rows if r["class"] in want and r["mode"] == mode and r["threshold"] == threshold]


def _fmt(s: dict) -> str:
    f = lambda v: "-" if v is None else f"{v:.2f}"  # noqa: E731
    return f"min {f(s['min'])} p50 {f(s['p50'])} max {f(s['max'])}, {s['empty']}/{s['n']} empty"


def _distribution(rows: list[dict], unanswerable: list[str]) -> tuple[dict, str]:
    """Per mode at threshold 0: class summaries and answerable-vs-unanswerable separation; plus default-threshold counts."""
    out: dict = {}
    parts = []
    for mode in MODES:
        a = _tops(rows, "answerable", mode, 0.0)
        u = _tops(rows, unanswerable, mode, 0.0)
        sep = separation(a, u)
        out[mode] = {
            "answerable": class_summary(a),
            **{c: class_summary(_tops(rows, c, mode, 0.0)) for c in unanswerable},
            "separation": sep,
        }
        parts.append(f"{mode}@0: answerable {_fmt(out[mode]['answerable'])}; unanswerable {_fmt(class_summary(u))}; AUC {sep['auc']:.2f}, gap {sep['gap']:+.2f}, separable {'yes' if sep['separable'] else 'no'}")
    default = {c: sum(1 for r in rows if r["class"] == c and r["mode"] == "hybrid" and r["threshold"] is None and r["n"] > 0) for c in unanswerable}
    out["hybrid_default_nonempty"] = default
    parts.append("hybrid at the default threshold, unanswerable queries returning something: " + ", ".join(f"{c} {k}/{len(CLASSES[c])}" for c, k in default.items()))
    return out, "; ".join(parts)


def _run_distribution(ctx: TestContext, label: str, unanswerable: list[str]) -> RunOutcome:
    p = ctx.provider
    if not p.capabilities().scores:
        return RunOutcome("SKIPPED", notes="provider exposes no similarity scores: no abstention signal available to developers")
    cps: list = []
    scope, err = _seed(ctx, label, cps)
    if err:
        return err
    rows = _collect(p, scope, ["answerable", *unanswerable], MODES, (0.0,)) + _collect(p, scope, ["answerable", *unanswerable], ("hybrid",), (None,))
    found = _precondition(rows)
    cps.append({"step": "precondition", "answerable_retrieved": found, "required": MIN_RETRIEVABLE})
    if found < MIN_RETRIEVABLE:
        return RunOutcome("INCONCLUSIVE", cps, notes=f"only {found} of 20 answerable queries retrieved their fact at threshold 0; the seed is not usable", extra={"rows": rows})
    summary, notes = _distribution(rows, unanswerable)
    return RunOutcome("DOCUMENTED", cps, notes=notes, extra={"rows": rows, "summary": summary})


# --- ABS-01 ---------------------------------------------------------------------------------


def abs_01(ctx: TestContext) -> RunOutcome:
    """20 facts stored. Ask 20 answerable and 20 near-miss questions (same domain, never stated)."""
    return _run_distribution(ctx, "abs01", ["near_miss"])


# --- ABS-02 ---------------------------------------------------------------------------------


def abs_02(ctx: TestContext) -> RunOutcome:
    """Off-domain and nonsense questions, with the answerable ones as the reference."""
    return _run_distribution(ctx, "abs02", ["off_domain", "nonsense"])


# --- ABS-03 ---------------------------------------------------------------------------------


def abs_03(ctx: TestContext) -> RunOutcome:
    """Documented `threshold` parameter: does raising it remove junk without removing the answers?"""
    p = ctx.provider
    if not p.capabilities().threshold:
        return RunOutcome("SKIPPED", notes="provider documents no threshold parameter")
    if not p.capabilities().scores:
        return RunOutcome("SKIPPED", notes="provider exposes no similarity scores")
    cps: list = []
    scope, err = _seed(ctx, "abs03", cps)
    if err:
        return err
    rows = _collect(p, scope, list(CLASSES), ("hybrid",), SWEEP)
    found = _precondition(rows)
    cps.append({"step": "precondition", "answerable_retrieved": found, "required": MIN_RETRIEVABLE})
    if found < MIN_RETRIEVABLE:
        return RunOutcome("INCONCLUSIVE", cps, notes=f"only {found} of 20 answerable queries retrieved their fact at threshold 0; the seed is not usable", extra={"rows": rows})

    unanswerable = ["near_miss", "off_domain", "nonsense"]
    sweep: dict = {}
    for t in SWEEP:
        at = [r for r in rows if r["threshold"] == t]
        ans = [r for r in at if r["class"] == "answerable"]
        un = [r for r in at if r["class"] in unanswerable]
        sweep["omitted" if t is None else f"{t:g}"] = {
            "answerable_any": sum(1 for r in ans if r["n"] > 0) / len(ans),
            "answerable_correct": sum(1 for r in ans if r["correct"]) / len(ans),
            "unanswerable_any": sum(1 for r in un if r["n"] > 0),
            "unanswerable_total": len(un),
            **{f"{c}_any": sum(1 for r in un if r["class"] == c and r["n"] > 0) for c in unanswerable},
        }
    base = {(r["q"]): r for r in rows if r["threshold"] == 0.0}
    same_omitted_vs_03 = all(
        r["ids"] == next(x for x in rows if x["q"] == r["q"] and x["threshold"] == 0.3)["ids"] for r in rows if r["threshold"] is None
    )
    server_equals_client = {}
    for t in (0.3, 0.4, 0.5, 0.6, 0.7, 0.8):
        ok = 0
        total = 0
        for r in rows:
            if r["threshold"] != t:
                continue
            b = base[r["q"]]
            expected = sorted(i for i, score in b["hits"] if score is not None and score >= t)
            total += 1
            ok += expected == r["ids"]
        server_equals_client[f"{t:g}"] = f"{ok}/{total}"
    summary = {"sweep": sweep, "omitted_equals_0.3": same_omitted_vs_03, "server_filter_equals_client_filter": server_equals_client}
    line = lambda k, v: f"t={k}: answerable correct {v['answerable_correct']:.0%}, unanswerable with results {v['unanswerable_any']}/{v['unanswerable_total']}"  # noqa: E731
    notes = "; ".join(line(k, v) for k, v in sweep.items()) + f"; omitted == 0.3: {same_omitted_vs_03}; server filter == client filter of threshold-0 results: {server_equals_client}"
    return RunOutcome("DOCUMENTED", cps, notes=notes, extra={"rows": rows, "summary": summary})


ABS_01 = TestDef("ABS-01", "ABS", "Near-miss questions vs answerable (score distributions)", abs_01)
ABS_02 = TestDef("ABS-02", "ABS", "Off-domain and nonsense questions", abs_02)
ABS_03 = TestDef("ABS-03", "ABS", "Threshold sweep", abs_03)

TESTS = [ABS_01, ABS_02, ABS_03]


@pytest.mark.parametrize("test", TESTS, ids=lambda t: t.id)
def test_abs(test, check):
    check(test)
