# memtrust decisions

Resolved during the PRD review. Where this file and `prd.md` disagree, this file wins. Verdict thresholds in D1 and D2 are the pre-registered ones: commit them and tag `prereg-v1` before the first real run. Later changes are amendments (see D1), never silent edits.

## D1. Pre-registered verdict thresholds

- Commit the thresholds in `docs/guarantees-matrix.md` and tag the commit `prereg-v1` before the first run.
- Changing a threshold after seeing data requires a visible amendment with the reason. Report results under both the old and the new threshold.
- The Day-1 smoke test (add, search, delete) happens before the commit. It is excluded from results, and the report says what was observed in it.
- Always publish raw time-to-consistency, whatever the verdict, so readers can apply their own threshold.

### Deletion (DEL)

| Outcome | Verdict |
|---|---|
| Gone by 120s, or by the docs' stated delay if longer | PASS |
| Present at 120s, gone by 600s | SLOW: report as S3 (docs/DX) unless the docs promised faster |
| Present at 600s, or never gone | FAIL (S1 candidate) |
| Present in some runs only | INCONCLUSIVE (**replaced before the freeze, see below**) |

If the docs promise immediate deletion, the docs' number replaces 120s.

**Confirmed before the freeze (2026-10-30):** a run still present at 600s is a privacy failure whatever the other runs did. Any such run makes the DEL result FAIL (S1 candidate, reported privately after the 3/3 re-check, docs check and issue-tracker check in the PRD). INCONCLUSIVE is not used for DEL or ISO. It stays for non-privacy categories. `docs/guarantees-matrix.md` section 2.1 and `aggregate()` in `src/runner.py` implement this, and `selftest/test_runner.py` covers it.

## D2. Isolation (ISO)

- Zero tolerance. Scoping is a query filter, so eventual consistency is not an excuse for a cross-tenant leak.
- Any leak in any run is a FAIL candidate. Report how many of the 3 runs showed it.
- A leak in 1 of 3 runs is reported privately as "intermittent". It is not downgraded to INCONCLUSIVE.
- Exception: ISO-02 (no scope specified) is characterization only. Mark it DOCUMENTED if the behavior is by design.

## D3. Corrections (COR): assertion depends on the surface

Decided on Day 1 after reading the docs.

- If the API exposes extracted memories or a profile (relational versioning: updates/extends/derives), test whether the newer fact is the current one on that surface.
- If only raw chunk search is available, COR is limited to what it can show deterministically: the new fact is retrievable, and its rank relative to the old one.
- Use unique fake values (e.g. `Zorvania-ZQ123`) so matching is unambiguous.
- Never report "stale fact returned" as a bug from chunk search alone. Mark that claim SKIPPED (surface unavailable) and say so.

## D4. Abstention (ABS): mechanical metric only

- Run answerable control queries and unanswerable queries over the same seeded data.
- Compare the top-result score distributions. Report whether any threshold separates them, or how much they overlap.
- If the API exposes no scores, the finding is "no abstention signal available to developers" (S3), and the metric is SKIPPED.
- The "could this mislead an LLM" judgment moves to a clearly labeled qualitative appendix. It is not in headline numbers.
- This replaces the false-evidence rate in PRD 5.4.

## D5. Poisoning (POI): LLM part is optional and capped

- POI-01 and POI-02 (how stored instructions are returned, no LLM) are the part worth keeping.
- POI-03 and POI-04 are the first cut if time or budget gets tight.
- Key from env var `LLM_API_KEY`, never committed.
- Model: `claude-haiku-5-5` if Anthropic API credit is available, otherwise a free-tier small model. Check current pricing; do not quote it from memory.
- Hard spend guard in code: estimate tokens before the run and abort above ~$0.20.
- Report the exact model and date. One model's obedience rate is one data point, not a general claim.

## D7. Stack: Python 3.11+ and pytest (replaces TypeScript/Bun)

- Decided 2026-10-30, after the TypeScript skeleton was built and before any live run. The author is faster in Python.
- Official `supermemory` Python SDK 5.x, pinned. Retries off, raw responses captured by an httpx hook. Differences from the TypeScript SDK: `docs/sdk-notes.md`.
- Two test kinds: `selftest/` (mock provider, virtual time, no network) proves the harness reports PASS and FAIL correctly; `tests/` are the product tests.
- Naming exceptions forced by Python: `assert.ts` became `assertions.py` (`assert` is a reserved word); the test files are `tests/test_<category>.py` (pytest discovery).
- Consequence for G4: MemoryBench is TypeScript/Bun, so the PR becomes "issue plus porting plan first".
- The TypeScript files were removed after the Python smoke cycle passed against the real API (`docs/smoke-observations.md`). They never ran against the real API, so the parity check was on a shared HTTP mock only.

## D6. Timeline: finish what can be finished in about 48h

The 4-day plan is the ceiling, not the target. Priority order, cutting from the bottom:

1. Day-1 recon, `api-facts.md`, `guarantees-matrix.md`, the `prereg-v1` tag
2. DEL, ISO
3. COR, LAT
4. ABS
5. POI-01/02
6. POI-03/04, CON stretch

Ship a rough public v0 with whatever categories are complete. The README states which are future work. Any S1 finding still follows the private-disclosure process in PRD section 10 before details go public.
