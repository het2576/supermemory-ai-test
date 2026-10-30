# Day-1 smoke observations

One add -> wait -> search -> delete -> confirm-gone cycle against the real API, run 2026-10-30 with `python -m scripts.smoke` (supermemory Python SDK 5.0.1, API v5, free plan key). Raw exchanges: `smoke/smoke-supermemory-20261030T081514Z.json`.

**Excluded from results** (`decisions.md` D1): this ran before the thresholds were frozen. It is reported here so nobody can say it was hidden. It is one run, one document, one search mode (`hybrid`), `dreaming` left at its default.

| Step | Observed |
|---|---|
| Add | HTTP 200, `{"id": "...", "status": "queued"}`, 1.3s round trip |
| Status | `queued` for ~8s, `done` at 9.2s after the add. `dreamingStatus` was `dreaming` while `queued`. |
| Searchable | First search after `status: done` already returned the canary chunk (similarity 0.772, `isLatest: true`, `isInference: false`). Searched only after `done`, so this says nothing about search before `done`. |
| Delete | HTTP 200, `{"count": 1, "errors": []}` |
| Gone from search | First search after the delete (t=0) returned `{"results": []}`. One data point; not a deletion verdict. |
| Namespace cleanup | `DELETE /ns/{ns}` returned HTTP 200 `{"status": "deleted", "deletedDocumentsCount": 0, "deletedMemoriesCount": 0}` with this key, so namespace delete works on the free plan. |

What this settles about the harness: response shapes match the docs and the SDK models (`system.status`, `system.dreamingStatus`, `count`/`errors`, `similarity`, `isLatest`); the key never appears in evidence files; per-call latency from this machine was roughly 400 to 700 ms.

What it does not settle: anything about DEL, ISO, COR, ABS or LAT as behaviors. Those need the pre-registered runs.
