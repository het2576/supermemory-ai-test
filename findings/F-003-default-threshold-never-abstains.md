# F-003: the default search `threshold` (0.3) never abstains; similarity scores are not calibrated for "I don't know"

**Status: final for this setup** (3 runs, `results/runs/2026-10-30/ABS-0*.json`; generated tables in REPORT.md).
**Severity (PRD section 10): S3** (developer experience / documentation). Not a bug: the parameter works exactly as documented. The gap is guidance.
**Novelty:** no matching upstream issue was looked for beyond the docs (this is a property of the scoring, not a defect report).

## What was observed

20 short first-person facts stored in one namespace. 55 queries: 20 answerable, 20 near-miss (same domain, never stated), 10 off-domain (general knowledge), 5 nonsense strings.

- **At the default threshold every unanswerable query returned results: 35 of 35, in all 3 runs**, including `zxqvk blorptangle 7731`.
- With `threshold: 0` (nothing hidden), top `similarity`: answerable 0.65 to 0.76 (p50 0.70, n=60); near-miss 0.54 to 0.655 (p50 0.60, n=60); off-domain 0.45 to 0.52 (p50 0.49, n=30); **nonsense 0.55 to 0.60 (p50 about 0.58 to 0.59, n=15)**. Nonsense scored above off-domain questions.
- Near-miss versus answerable (hybrid): AUC 0.993, gap -0.003, so the ranges touch. Off-domain and nonsense separate from answerable (gap +0.134 and +0.057) in chunk and hybrid modes, but not in `memories` mode for nonsense (gap -0.063).
- Threshold sweep on all 55 queries (hybrid), per run: at 0.5, 29 of 35 junk queries still returned results; at 0.6, 13 to 16; at 0.7, none, but only 45 to 50% of answerable queries still returned their correct fact; at 0.8, none and 0%.
- By the pre-registered reading rule (zero junk in every run while keeping at least 90% of the answers), **no threshold in the grid qualifies**. The best split found after the fact is about 0.655 (keeps 92% of answerable, removes 100% of near-miss). The usable window is about 0.003 wide and was tuned on the same 55 queries, so it is not a recommendation.
- The `threshold` parameter itself behaves as documented: the server-side filter equalled filtering the threshold-0 results by `similarity >= t` on 55 of 55 queries at every tested value, and omitting it equalled 0.3 in all 3 runs.

## What the docs say

`threshold` is a 0 to 1 value, default 0.3 ("was 0.6 in v4"), "higher means fewer, better results" (docs/api-facts.md section 4, from the search reference). Nothing says what scores to expect for an unanswerable query, that the default will return results for any input, or how to choose a value.

## Why it matters

An app that treats "search returned something" as "the memory knows" will answer confidently from unrelated text. The default returns something for everything, here even for gibberish, because the corpus is small and the embedding scale sits high. The v4 default of 0.6 would still have returned 13 to 16 of the 35 junk queries (depending on the run) in this setup, so this is not only a regression from the default change.

## Suggested fix (for the vendor to judge)

Say plainly in the search docs that results are always returned above 0.3, show a score distribution for answerable versus unanswerable queries on a sample corpus, and recommend either a calibrated threshold per corpus or a margin test (top score versus the next score) instead of a fixed number.

## Caveats

Free plan, one account, 20 short facts, English only, one embedding model chosen by the service, one day. A larger or more varied corpus will shift the score scale; this characterizes the setup, not retrieval quality in general. The "could this mislead a model" question is not answered here (D4); the top returned text for each unanswerable query is in the evidence files for a qualitative review.
