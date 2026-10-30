# memtrust

Black-box, repeatable tests for the production behaviors of AI memory APIs that benchmarks like LongMemEval do not cover: **deletion**, **tenant isolation**, **corrections**, **abstention**, **stored-text handling** and **latency**. First target: [Supermemory](https://supermemory.ai) (v5 API, official Python SDK).

Every claim in the report links to a raw evidence file. Thresholds were written down before the runs (git tags `prereg-v1`, `prereg-cor`, `prereg-lat`, `prereg-abs`, `prereg-poi`, `prereg-del06`), and every later change is a visible amendment with its reason.

**Results and caveats: [REPORT.md](REPORT.md).** Short version for the vendor: [CRITIC.md](CRITIC.md).

## Run it in five minutes

You need Python 3.11+ and, for the real tests, a Supermemory API key (the free plan is enough).

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

pytest                       # 1. harness self-tests: mock provider, virtual time, no network, a few seconds
```

```bash
cp .env.example .env         # 2. put your key in .env (it is gitignored; never paste it anywhere else)
python -m src.runner --only DEL-01 --runs 1      # one real test, one to two minutes
python -m src.runner --only DEL,ISO              # whole categories, 3 runs each (the default)
python -m src.report                             # tables from results/, no hand-typed numbers
```

Use a **throwaway account or key**. The tests create namespaces named `memtrust_*`, fill them with fake data, and delete only those afterwards. They never touch anything else, but they do write to and delete from whatever account the key belongs to. The official runs in this repo made about 6,000 requests in total (ABS and LAT are the heaviest, DEL the lightest), so check your plan's limits and pricing before running everything. Nothing here is a load test: calls are paced at about five per second and run one at a time.

Evidence lands in `results/runs/<date>/<TEST>-run<n>.json` with the exact request/response exchanges (the API key is stripped), the checkpoints, and the verdict.

## What is tested

| Category | Question | Tests |
|---|---|---|
| DEL | After a delete, does the content stop coming back, how fast, and does a namespace delete remove what a document delete preserved? | DEL-01..06 |
| ISO | Can one tenant ever see another's content: search, near-duplicates, look-alike IDs, profiles? Zero tolerance. | ISO-01..05 |
| COR | When a fact changes, is the current one served? Explicit, implicit, chains, "used to X, now Y", retraction. | COR-01..06 |
| ABS | Does the API give a signal to say "I don't know"? Score distributions and a threshold sweep. | ABS-01..03 |
| POI | How does stored instruction-like or role-impersonating text come back, and is it marked? Characterization only. | POI-01..02 |
| LAT | Ingest, memory and search timings, with p50, p95, max and n. Numbers only. | LAT-01..04 |

Verdicts: `PASS`, `FAIL`, `SLOW` (deletion only), `INCONCLUSIVE`, `DOCUMENTED` (characterized, no pass/fail), `SKIPPED` (a precondition failed, so the harness refused to judge), `ERROR` (the harness, not the product). A skipped or errored run is never counted as a pass.

Not covered: the LLM-in-the-loop poisoning tests (POI-03/04), concurrency, other providers, large or non-text documents, anything beyond the free plan.

## Why you can trust a PASS

- **Preconditions first.** Every test proves its data was retrievable before checking that it is gone, isolated, corrected or marked. "Nothing came back" can never pass on its own.
- **The harness is tested too.** `selftest/` runs every test against an in-memory mock with injectable bugs (deletes that do nothing, cross-tenant leaks, stale facts, data that returns late, a threshold that is ignored). Each bug must flip exactly the tests it should, and the test logic itself was mutation-checked: break the code on purpose and confirm a self-test fails.
- **Raw evidence, scrubbed.** Nothing in the report is typed by hand; `src/report.py` builds the tables from the evidence files.
- **Failures are reported, not tuned away.** Superseded attempts (a network error, a skipped run) are kept under `results/superseded/` with the reason.

## Layout

```
src/adapter.py          the provider interface (add, search, delete, status, profile, ...)
src/providers/          supermemory.py (official SDK) and mock.py (for the self-tests)
src/runner.py           runs tests 3x, writes evidence, aggregates verdicts
src/report.py           evidence -> tables
src/{deletion,corrections,latency,abstention,poison}.py   shared logic per category
tests/                  the product tests, one file per category
selftest/               harness tests against the mock
docs/                   api-facts, guarantees matrix, decisions and amendments, SDK notes
findings/               write-ups with evidence, docs check and issue-tracker check
results/                evidence (runs/), superseded attempts, supplementary samples
```

## Testing another memory API

Implement the `MemoryProvider` protocol in `src/adapter.py` (a handful of methods; optional ones such as `forget`, `search_unscoped` and `last_latency_ms` make more tests applicable and are otherwise skipped), register it in `make_provider` in `src/runner.py`, and run the same suite. Do not copy a guarantee from this repo to another vendor: read their docs first and write the matrix row before the run (`docs/guarantees-matrix.md`).

## Honest limits

One free-plan account, one machine and region, one day, short English text. The results describe that setup. The suite shows what it can observe through the API; it cannot see backups or internal stores, so "gone from every surface" is not "erased".
