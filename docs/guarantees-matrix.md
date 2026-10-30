# Guarantees matrix and pre-registered thresholds

Status: **FROZEN at git tag `prereg-v1`** (2026-10-30), before any DEL, ISO, COR, ABS, POI or LAT run. The only live call so far is the Day-1 smoke cycle (`docs/smoke-observations.md`), excluded from results. Edits after the tag are visible amendments with a reason, and results are reported under both the old and new threshold (`decisions.md` D1).

Facts come from `docs/api-facts.md` (docs read 2026-10-30, SDK `supermemory` 5.0.3, API v5). Where a cell says **unknown**, the docs are silent and the live run is what finds out.

## 1. Behavior, promise, test

| Behavior | What the docs promise | How memtrust tests it | Test IDs |
|---|---|---|---|
| Deletion | "Deletes are permanent." Derived memories of a deleted document "are forgotten." No stated delay. | Add canary doc, wait for `done`, delete, then search (`chunks`, `memories`, `hybrid`) at checkpoints until gone or 600s. Also list `type=memories` with `include.forgotten`. | DEL-01..05 |
| Deletion while processing | Delete of a processing doc is rejected: `Document is still processing`. | Delete immediately after add. Expect an error entry, not silent success. Then confirm the doc still completes and is not half-deleted. | DEL-04 |
| Isolation | Namespace is a hard boundary; dedicated index per namespace; "never returned by a search scoped to another namespace." | Two namespaces with distinct canaries, cross-search, near-duplicates, look-alike IDs, profile and list endpoints. | ISO-01..05 |
| Updates | New fact "replaces what was true before for search"; `isLatest` marks the current fact. | Use `searchMode: "memories"` and `isLatest`. Unique fake values. Needs `dreaming: "instant"` for determinism; one run per category with default `dynamic` to measure the gap. | COR-01..05 |
| Abstention | `similarity` is returned and `threshold` is a parameter (default 0.3). | Seed 20 facts, run answerable and unanswerable queries, compare top-score distributions, then test a threshold sweep. | ABS-01..03 |
| Stored instructions | Not discussed. Retrieval returns stored text. | Record how instruction-like and role-impersonating text is returned (field, type, attribution). No LLM in POI-01/02. | POI-01/02 |
| Latency | "Seconds" for short chat turns; "several minutes" for a fresh namespace's memories; ~sub-300ms p50 search. No SLA. | Add N items, poll document `status` at 1s and run a verification search on `done`; also time `dreamingStatus`. | LAT-01..03 |

## 2. Pre-registered verdict rules

### 2.1 DEL (deletion)

Measured: time from the delete call returning to the first checkpoint at which the canary is absent from all three search modes (`chunks`, `memories`, `hybrid`), polled at 0, 5, 30, 120, 300, 600s.

| Outcome (per run) | Run verdict |
|---|---|
| Absent by 120s | PASS |
| Present at 120s, absent by 600s | SLOW |
| Present at 600s, or never absent | FAIL |

| Across the 3 runs | Final verdict |
|---|---|
| 3 PASS | PASS |
| Any SLOW, no FAIL | SLOW: report as S3 (docs/DX) unless the docs promise faster |
| **Any FAIL** | **FAIL (S1 candidate), reported privately first.** The count `n/3` is stated. |
| Mixed PASS and SLOW | SLOW, with the spread reported |

Docs rule: if the docs state a delay, that number replaces 120s. If they promise immediate deletion, 120s becomes that promise. At the time of writing they state neither.

**This replaces the original `decisions.md` D1 row** ("present in some runs only: INCONCLUSIVE"), confirmed before the freeze: a run still present at 600s is a privacy failure whether or not the other runs were clean, so it is never downgraded to INCONCLUSIVE. INCONCLUSIVE is kept only for non-privacy tests.

Always report raw time-to-consistency (per run, per search mode) whatever the verdict.

### 2.1a Amendment A1 (made after the `prereg-v1` tag, before any DEL, ISO, COR, ABS, POI or LAT run)

These two points were not spelled out in 2.1 and are fixed here before the first product-test run, so they cannot be tuned to results. No threshold changed.

1. **Which surfaces count.** "Present" means the content (the canary, or for DEL-02/03 a unique fake name that only that document contains) comes back from any normal retrieval surface: `search` in `chunks`, `memories` or `hybrid` mode, and for DEL-03 also the profile. Evidence-only surfaces never decide a verdict: search with `include.forgotten`, and the memories list with `include.forgotten`. The docs describe forgotten memories as soft-deleted and preserved, so their presence there is recorded as documented behavior.
2. **Stays gone.** The first checkpoint at which nothing is present must hold on one more probe 10 seconds later. If the content reappears, that is recorded (`reappeared: true`), the watch continues on the normal schedule, and the time-to-consistency is the first checkpoint that holds.

### 2.2a Amendment A2 (made after the first ISO run, before any COR, ABS, POI or LAT run)

The first ISO-05 attempt (2 PASS, 1 SKIPPED, aggregate INCONCLUSIVE) was skipped in run 3 because Supermemory's memory extractor altered the test token: `ZQ-ISO-bfca9b4a60ab` was stored as `ZQ-ISO-bfca9b60ab`. The skip guard worked (no false pass), but it left only two valid runs. For tests that need a derived memory or profile entry to carry the token (ISO-05 and, from now on, COR), the harness now retries up to 3 times with a fresh token and scope, records every attempt, and SKIPs only if all attempts fail. No pass/fail threshold changed. The first attempt's files are kept under `results/superseded/`. DEL-03 was not changed (all its tokens survived extraction).

### 2.2 ISO (isolation)

| Outcome | Verdict |
|---|---|
| No foreign canary in any result, any checkpoint, all 3 runs | PASS |
| Foreign canary in any result, any checkpoint, any run | FAIL candidate. Report `n/3` runs and the checkpoint. 1/3 is reported privately as "intermittent". |
| ISO-02 (no scope) | Characterization only. v5 has no unscoped route, so test legacy routes if they accept no tag. DOCUMENTED if by design, SKIPPED if no such route works. |

A namespace rejected by validation (space, `/`, `@`) is not a leak; it is a pass for ISO-04's "no normalization collision" check as long as the rejection is an error and not a silent rewrite into another tenant's ID.

### 2.3 COR (corrections)

| Surface available | Assertion |
|---|---|
| Memories (`searchMode: "memories"` with `isLatest` and `include.related`) | New fact present with `isLatest: true`; old fact absent or `isLatest: false`. |
| Chunks only | New fact retrievable; rank of new vs old recorded. "Stale fact returned" is **not** reported as a bug from chunk search. Mark SKIPPED (surface unavailable). |

Values are unique fake tokens (e.g. `Zorvania-ZQ<uuid>`). Memory generation is asynchronous, so poll `dreamingStatus` and the memory surface up to 300s before judging.

### 2.4 ABS (abstention)

Mechanical only. Seed one namespace, run answerable control queries and unanswerable queries, record the top-result `similarity` for each, and report the overlap of the two distributions, whether any `threshold` value separates them, and how many unanswerable queries return a nonempty result at the default 0.3. The "could this mislead an LLM" judgment is a labeled qualitative appendix, never a headline number.

### 2.5 POI (poisoning)

POI-01/02 record how stored text is returned (field names, any typing or marking, any attribution). POI-03/04 are optional (see `decisions.md` D5).

### 2.6 LAT (latency)

Time to `status: "done"` and time to first search hit are recorded separately, plus time to `dreamingStatus: "done"`. Report p50, p95 and max. No verdict; numbers only.

### 2.7 Result states

PASS, FAIL, SLOW (DEL only), INCONCLUSIVE (non-privacy tests only, 1 or 2 of 3), DOCUMENTED (behavior differs from expectation but the docs state it), SKIPPED (surface or feature unavailable), ERROR (the harness threw, e.g. a network failure; never counted as a product finding and re-run before any conclusion).

Per-run verdicts combine in `aggregate()` in `src/runner.py`, which implements the table in 2.1 and the DEL/ISO "any FAIL is FAIL" rule.

## 3. Test-design changes forced by the docs

| PRD item | Change | Why |
|---|---|---|
| DEL-04 delete during processing | Becomes "does the API reject it and leave the doc intact", not "never becomes searchable". | Docs: processing docs cannot be deleted; they come back in `errors`. |
| DEL-03 derived facts | Check `memories` list with `include.forgotten`, search with and without `include.forgotten`, and profile. | Docs say derived memories are forgotten on document delete, but forgetting is a soft delete. |
| DEL-05 re-add | Re-add under the same `id` after delete and under a new `id`. | Same `id` "appends/links"; check it does not resurrect old state. |
| ISO-02 no scope | v5 requires a namespace in the path. Legacy routes only. | Docs. |
| ISO-04 look-alike IDs | Valid look-alikes only: `user_1`, `user_10`, `user_1:x`, `User_1`, `user-1`, `user_1_`. Invalid ones (trailing space, `/`, `@`) test rejection. | Pattern `^[a-zA-Z0-9_:-]+$`. |
| ISO-05 profile bleed | `POST /ns/{ns}/profile` after seeding both namespaces. Needs `dreaming: "instant"`. | Docs. |
| COR timing | Use `dreaming: "instant"` for determinism, plus a smaller default-mode sample. | Docs: default can take minutes. |
| LAT polling | Poll document status (1s), verify with search at `done` and at 5s steps afterward, not search every second. | Keeps call volume well under 500/min. |
| CON-01 duplicates | Same `id` twice vs same content, different `id`. | Docs describe `id`-based dedup. |

## 4. Cost and volume

Rough budget at list rates: roughly 1,500 to 2,500 API calls over the whole suite, about 150K ingest tokens at most. That is well under 1 USD against 5 USD of credit. Request rate must stay under 500/min per key; the runner paces itself to about 5/s.

## 5. What this suite cannot test from the outside

- That customer content is never used for training.
- Encryption at rest, SOC 2, and similar compliance claims.
- Behavior of connectors (not on the free plan).
- Org-level controls (restricted members, scoped keys need an org admin key; scoped-key isolation can be tested on a free plan only if keys can be minted there, which is **unknown**).
