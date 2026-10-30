"""Analysis helpers for the POI tests. Protocol: docs/decisions.md D11 (pre-registered, tag `prereg-poi`).

Characterization only: these functions describe how planted text comes back; none of them judges it."""

from __future__ import annotations

import re
from typing import Any, Sequence

from .adapter import MemoryProvider, SearchOptions

DOCUMENTED_KEYS = {"id", "memory", "chunk", "metadata", "similarity", "isLatest", "isInference", "system", "included"}
MARK_WORDS = ("untrusted", "user-provided", "source:")
_DATE_PREFIX = re.compile(r"^\[\d{4}-\d{2}-\d{2}\]\s*")  # the profile prefixes entries with a date; that is not a trust label
SURFACES = ("chunks", "memories", "hybrid")


def form(texts: Sequence[str], canary: str, phrase: str) -> str:
    """verbatim: the planted wording survives. rewritten: the canary survives inside different wording. absent: neither."""
    with_canary = [t for t in texts if canary in t]
    if not with_canary:
        return "absent"
    return "verbatim" if any(phrase.lower() in t.lower() for t in with_canary) else "rewritten"


def marked_in_text(text: str) -> bool:
    """A wrapper, delimiter or trust label added around the returned text."""
    body = _DATE_PREFIX.sub("", text).lstrip()
    return body.startswith(("<", "[")) or any(w in text.lower() for w in MARK_WORDS)


def _surface(texts: list[str], canary: str, phrase: str, cues: Sequence[str]) -> dict[str, Any]:
    hit = [t for t in texts if canary in t]
    return {
        "returned": bool(hit),
        "form": form(texts, canary, phrase),
        "texts": hit[:3],
        "cues_kept": [c for c in cues if any(c.lower() in t.lower() for t in hit)],
        "marked_in_text": any(marked_in_text(t) for t in hit),
    }


def analyze(p: MemoryProvider, scope: str, query: str, canary: str, phrase: str, cues: Sequence[str]) -> dict[str, Any]:
    """How one planted document comes back on every surface."""
    report: dict[str, Any] = {}
    for mode in SURFACES:
        hits = p.search(scope, query, SearchOptions(mode=mode)).hits  # type: ignore[arg-type]
        items = [h for h in hits if canary in h.text]
        out = _surface([h.text for h in hits], canary, phrase, cues)
        raws = [h.raw for h in items if isinstance(h.raw, dict)]
        keys = sorted({k for r in raws for k in r})
        out.update(
            kinds=sorted({h.kind for h in items}),
            fields=keys,
            extra_fields=[k for k in keys if k not in DOCUMENTED_KEYS],
            metadata_keys=sorted({k for r in raws for k in (r.get("metadata") or {})}),
            is_inference=[h.is_inference for h in items],
        )
        report[mode] = out
    if p.capabilities().profiles:
        report["profile"] = _surface(p.profile(scope).entries, canary, phrase, cues)
    return report


def any_marking(report: dict[str, Any]) -> bool:
    """True if any surface shows a marking in the text or a field outside the documented set."""
    return any(s.get("marked_in_text") or s.get("extra_fields") for s in report.values())


def describe(name: str, report: dict[str, Any]) -> str:
    forms = ", ".join(f"{s} {r['form']}" for s, r in report.items())
    cues = sorted({c for r in report.values() for c in r["cues_kept"]})
    return f"{name}: {forms}; role cues kept {cues or 'none'}; marking {'found' if any_marking(report) else 'none'}"
