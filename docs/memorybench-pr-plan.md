# MemoryBench: issue and porting plan

Goal: make memtrust useful to MemoryBench. This is an **issue plus a porting plan**, not a PR, because MemoryBench is TypeScript/Bun and memtrust is Python, and because the current MemoryBench interfaces cannot express most of the suite. Facts below were read on 2026-10-31 from the sources named; anything not stated there is marked **unknown**.

## What MemoryBench is (from its own pages)

Sources: [README](https://github.com/supermemoryai/memorybench), [benchmarks guide](https://raw.githubusercontent.com/supermemoryai/memorybench/main/src/benchmarks/README.md), [providers guide](https://raw.githubusercontent.com/supermemoryai/memorybench/main/src/providers/README.md).

- MIT licensed, Bun/TypeScript. Providers: supermemory, mem0, zep. Benchmarks: locomo, longmemeval, convomem. Pipeline: ingest, index, search, answer, evaluate, report. Evaluation is judge-model based; the headline numbers are accuracy and a MemScore triple (accuracy, average search latency, context tokens).
- A **benchmark** implements `Benchmark`: `name`, `load()`, `getQuestions()`, `getHaystackSessions(questionId)`, `getGroundTruth(questionId)` (a string), `getQuestionTypes()`, plus optional `getContainerKey`, `headlineExcludedTypes`, `searchLimit`, `buildAnswerPrompt`, `buildJudgePrompt`. Registration: a folder under `src/benchmarks/`, an entry in `src/benchmarks/index.ts`, a name in `BenchmarkName` (`src/types/benchmark.ts`). Every test case is a question with a ground-truth answer.
- A **provider** implements `Provider`: `initialize`, `ingest(sessions, options)`, `awaitIndexing(result, containerTag)`, `search(query, options)` returning `unknown[]`, and `clear(containerTag)`.
- No CONTRIBUTING file or issue template is mentioned. **Unknown:** the maintainers' preferred workflow for new benchmarks.

## Why memtrust does not drop in

| memtrust category | Needs | In MemoryBench today |
|---|---|---|
| COR (corrections) | add facts in order, ask for the current value | Fits the question/ground-truth shape. A haystack with a fact and its correction, ground truth = the new value. Nothing new needed in `Provider`. |
| ABS (abstention) | similarity scores, a `threshold` option, unanswerable questions | `search` returns `unknown[]`, so scores are provider-specific. Unanswerable questions fit the QA shape, but the score analysis does not. **Unknown:** whether the LongMemEval data already includes abstention questions here; check before proposing. |
| DEL (deletion) | delete one document, wait, confirm gone; delete a namespace | `Provider` has no per-document delete. `clear(containerTag)` exists, but "what it does to documents still indexing" is not described. |
| ISO (isolation) | two tenants, cross-search, look-alike IDs | Needs two containers and a way to search one while holding data in another; container creation rules are not described. |
| LAT (latency) | per-call timing, time to searchable, time to memory | MemScore already includes average search latency; time-to-searchable and dreaming time are not measured. |
| POI (stored text) | inspect returned fields and wording | Needs raw result objects; `unknown[]` allows it. |

Two more mismatches to be upfront about: memtrust's checks are **deterministic** (unique tokens, string matching, no judge model), where MemoryBench scores with a judge; and memtrust asserts **behavior over time** (probes at 0, 5, 30 seconds and later), where a benchmark question is answered once.

## Proposed path, smallest step first

1. **Open an issue, not a PR.** Link the repo and the report, say plainly what it found and did not find, and ask one question: would they accept a "behavioral contract" track alongside the QA benchmarks? Draft below.
2. **If yes, start with COR as a QA-shaped benchmark** (`corrections`): no interface change, a few dozen haystacks with unique fake values, ground truth = the latest value, judged exactly (string match) or by the existing judge. The unique-token trick from memtrust carries over directly.
3. **Then propose optional, backwards-compatible provider capabilities** so existing providers are untouched: `capabilities()`, `delete(containerTag, ids)`, `status(containerTag, id)`, and `search` returning `{text, score}`. memtrust's `MemoryProvider` protocol (`src/adapter.py`) is the reference, with the same optional-method rule: a missing capability means the test is skipped, never passed.
4. **Port DEL and ISO last**, as a separate "contract" runner (not scored by a judge) that reuses the provider adapter and reports PASS/FAIL/SLOW with evidence.

Porting effort, honestly: the logic is small and declarative (query sets, token rules, checkpoint schedules), but the harness details that make results trustworthy (preconditions, retry-with-fresh-token, the mock provider with injectable bugs, mutation checks) are most of the work. Budget a few days for a TypeScript port of COR plus the capability interface; DEL/ISO need the interface change first.

## Draft issue (edit freely; it should sound like you)

> **Title:** Behavioral contract tests for memory providers (deletion, isolation, corrections, abstention)?
>
> I wrote a small black-box suite, memtrust, for things the QA benchmarks don't cover: whether a delete stops content coming back (and how fast), whether tenants can see each other, whether the current fact wins after a correction, and what the API gives you to say "I don't know". It's Python, deterministic (unique tokens, no judge), and every claim links to a raw evidence file. First target was Supermemory; results and caveats are in REPORT.md: [link].
>
> Two questions: (1) would a non-QA "contract" track fit MemoryBench, or is it out of scope? (2) the `Provider` interface has no per-document delete, status or scores, so I'd propose optional capabilities (a missing one means the test is skipped). A corrections benchmark needs no interface change and could come first. Happy to port that part to TypeScript if there's interest.
