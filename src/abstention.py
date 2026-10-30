"""Statistics for the ABS tests. Protocol: docs/decisions.md D10 (pre-registered, tag `prereg-abs`).

`top` is the highest similarity among a query's results, or None when nothing was returned. For ranking and
separation an empty result counts as -1.0: it carries no evidence, which is the best outcome for an unanswerable
query and the worst for an answerable one."""

from __future__ import annotations

from typing import Any, Sequence

from .latency import percentile

NO_RESULT = -1.0


def _v(top: float | None) -> float:
    return NO_RESULT if top is None else top


def class_summary(tops: Sequence[float | None]) -> dict[str, Any]:
    got = [t for t in tops if t is not None]
    return {
        "n": len(tops),
        "empty": len(tops) - len(got),
        "min": min(got) if got else None,
        "p50": percentile(got, 0.50),
        "max": max(got) if got else None,
    }


def auc(answerable: Sequence[float | None], unanswerable: Sequence[float | None]) -> float | None:
    """Probability that a random answerable query's top score exceeds a random unanswerable one's (ties count half)."""
    if not answerable or not unanswerable:
        return None
    wins = sum(1.0 if _v(a) > _v(u) else 0.5 if _v(a) == _v(u) else 0.0 for a in answerable for u in unanswerable)
    return wins / (len(answerable) * len(unanswerable))


def gap(answerable: Sequence[float | None], unanswerable: Sequence[float | None]) -> float | None:
    """min(answerable top) - max(unanswerable top). Positive means some threshold separates the two sets perfectly."""
    if not answerable or not unanswerable:
        return None
    return min(_v(a) for a in answerable) - max(_v(u) for u in unanswerable)


def best_threshold(answerable: Sequence[float | None], unanswerable: Sequence[float | None]) -> dict[str, Any] | None:
    """The observed score that best splits the two sets by balanced accuracy (ties: higher specificity, then lower t)."""
    if not answerable or not unanswerable:
        return None
    best: tuple[float, float, float, float] | None = None
    for t in sorted({_v(x) for x in [*answerable, *unanswerable] if x is not None}):
        sensitivity = sum(1 for a in answerable if a is not None and a >= t) / len(answerable)
        specificity = sum(1 for u in unanswerable if u is None or u < t) / len(unanswerable)
        cand = ((sensitivity + specificity) / 2, specificity, -t, t)
        if best is None or cand[:3] > best[:3]:
            best = cand
    if best is None:
        return None
    t = best[3]
    return {
        "threshold": t,
        "balanced_accuracy": best[0],
        "answerable_kept": sum(1 for a in answerable if a is not None and a >= t) / len(answerable),
        "unanswerable_removed": sum(1 for u in unanswerable if u is None or u < t) / len(unanswerable),
    }


def separation(answerable: Sequence[float | None], unanswerable: Sequence[float | None]) -> dict[str, Any]:
    g = gap(answerable, unanswerable)
    return {
        "auc": auc(answerable, unanswerable),
        "gap": g,
        "separable": g is not None and g > 0,
        "best": best_threshold(answerable, unanswerable),
    }


def reliably_removes_junk(per_run: Sequence[dict[str, float]], baseline_kept: float) -> bool:
    """D10 reading rule for one threshold: zero unanswerable queries return anything in every run, while the share of
    answerable queries whose correct fact is still returned stays at or above 90% of the threshold-0 baseline."""
    return bool(per_run) and all(r["unanswerable_any"] == 0 and r["answerable_correct"] >= 0.9 * baseline_kept for r in per_run)
