# F-002: default `dreaming: "dynamic"` produced no memory for about 4 hours (8 of 8 documents unavailable at 30 minutes; 5 of 5 arrived at 4h04m)

**Status: final for this setup.** The 2-hour follow-up watch was killed when the session ended, but the server's own timestamps on the leftover namespaces answer the question it was meant to answer (see "When the memories did arrive").
**Severity (scale in REPORT.md): S2/S3.** Not a privacy issue (no S1 process needed). In the default mode memories arrived about 4 hours after the document, and the docs set an expectation of "several minutes".
**Novelty: corroborates a report that is already public** (see "Upstream"). It is not a new discovery and should not be presented as one.

## What was observed

In the default mode, a document reaches `status: "done"` in about 27 seconds but `system.dreamingStatus` stays `"dreaming"` and no memory is returned by `searchMode: "memories"` for at least 30 minutes. With `dreaming: "instant"` the same kind of document has a memory about 25 seconds after `add` (LAT-03, pooled p50 26.1s, p95 33.8s, n=15; COR: 18 of 18 official runs).

| Sample | Setup | Result |
|---|---|---|
| COR-01 default-mode sample (`results/supplementary-dynamic/`) | 3 attempts, fresh namespace each, 1 short document each | `done` yes; `dreamingStatus` still `dreaming` after 15 min; no memory in a further ~15 min. 3 of 3. |
| LAT-04 (`results/runs/2026-10-30/LAT-04-run1.json`) | 3 namespaces at once: A 1 document, B 1 document, C 3 related documents about one subject | `done` at 26 to 28s for all 5; no `dreamingStatus: done` and no memory within the 1800s cap. 5 of 5. |

So 8 of 8 documents in 6 namespaces, across two separate sessions on the same day, had no memory at 30 minutes; the 5 documents that were not deleted afterwards got their memories about 4h 04m after `add`. Scope C (three related documents) also produced nothing, so "a lone document waits for a batch" does not explain it within 30 minutes.

## When the memories did arrive

The LAT-04 namespaces were left in place when the session ended. Reading them later (read-only; `results/supplementary-dynamic/server-timestamps-lat04.json`), every one of the 5 documents shows `status: done`, `dreamingStatus: done`, and a memory. The server's own timestamps give the delay from `add` to dreaming complete:

| Namespace | Documents | Added (UTC, 2026-10-30) | Dreaming done (UTC) | Delay |
|---|---|---|---|---|
| A | 1 | 17:45:53 | 21:49:27 | 4h 03m 34s |
| B | 1 | 17:45:54 | 21:49:30 | 4h 03m 36s |
| C | 3 related | 17:45:58 to 17:46:00 | 21:49:53 (all three, same millisecond) | 4h 03m 53s to 4h 03m 55s |

All three namespaces finished within 26 seconds of each other, about 4 hours after they were created. That points to a shared batch cycle on the service side, not a per-document wait, and it explains why neither the 30-minute caps nor a lone-versus-related document made any difference. It is **one batch event on one day**: it says nothing about whether the cycle is fixed, periodic or load-dependent, and the first 30-minute watch could not have seen it. Timestamps are `system.createdAt` / `updatedAt` as the API returns them; that `updatedAt` marks the end of dreaming is my reading of the fields, not something the docs state.

## What the docs say

- add-memories: "A fresh namespace can show zero memories and an empty profile for several minutes." (https://supermemory.ai/docs/ingestion/add-memories.md)
- how-it-works: dynamic groups related documents; "Memory extraction may continue after `status: "done"`." No schedule, idle rule or numeric bound is given. (https://supermemory.ai/docs/concepts/how-it-works.md)
- The same page recommends dynamic for real apps "because batching lets new memories connect to related ones."

"Several minutes" versus about four hours is the gap. There is no stated SLA, so this is a documentation and expectation problem, not a broken feature: the memories do arrive.

## Upstream

supermemoryai/claude-supermemory issue #156 (opened 2026-10-27, open, no labels, no reply when read): a Pro-workspace user reports `dreamingStatus: "dreaming"` with 0 memories after 15 minutes in dynamic mode, versus 4 memories after 40 seconds in instant mode, and asks for a setting to choose the mode. https://github.com/supermemoryai/claude-supermemory/issues/156
Related but different cause: supermemoryai/supermemory #1851 (a client dropped the `dreaming` field, fixed in #1853), and #1300 (a memory-agent timeout left a document `done` with 0 memories, closed as not planned).

## Caveats

Free plan, one account, one machine. Short single-sentence documents. One batch event observed, so the typical delay is unknown; a Pro plan may differ (the upstream report is on one). The issue above is on a different plan and client, which makes an account-specific cause less likely, but this suite cannot rule out a regional or load-related cause.

## Why it matters for the suite

Every test here that needs memories uses `dreaming: "instant"` (COR, ISO-05, LAT-03). That is the documented way to read memories right after `add`, but it costs one extra operation per document, and an app that keeps the default would see an empty memory surface and an empty profile for a long time. Chunk search is unaffected.
